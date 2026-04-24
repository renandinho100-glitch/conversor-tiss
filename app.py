import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import BytesIO

# --- CONSTANTES DE NEGÓCIO ---
NS = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
CODIGOS_GLOSA_PARA_1705 = ['1799', '9918', '1899']
CODIGOS_GLOSA_PADRAO = ['1099', '1199', '1999', '3099']

def extrair_metadados_para_site(retorno_file):
    """
    Função para alimentar os checkboxes do site.
    """
    try:
        tree = ET.parse(retorno_file)
        root = tree.getroot()
        lote_el = root.find('.//ans:numeroLotePrestador', NS)
        lote_id = lote_el.text if lote_el is not None else "Lote Único"
        
        guias = []
        for rel in root.findall('.//ans:relacaoGuias', NS):
            g_el = rel.find('.//ans:numeroGuiaPrestador', NS)
            if g_el is not None:
                guias.append(g_el.text.strip())
        
        return {lote_id: guias}
    except:
        return {}

def processar_xmls(envio_file, retorno_file, guias_selecionadas=None):
    """
    Gera o XML final filtrado. Se guias_selecionadas for None, processa tudo.
    """
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    ET.register_namespace('xsi', "http://www.w3.org/2001/XMLSchema-instance")

    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos: {e}"

    reg_ans_el = root_ret.find('.//ans:registroANS', NS)
    is_amazonia = reg_ans_el is not None and reg_ans_el.text == '419052'

    # 1. MAPEAMENTO DO RETORNO
    mapa_retorno = {}
    for relacao in root_ret.findall('.//ans:relacaoGuias', NS):
        n_guia_prest = relacao.find('.//ans:numeroGuiaPrestador', NS)
        n_guia_oper = relacao.find('.//ans:numeroGuiaOperadora', NS)
        carteira = relacao.find('.//ans:numeroCarteira', NS)
        senha = relacao.find('.//ans:senha', NS)
        
        meta = {tag: (relacao.find(f'ans:{tag}', NS).text.strip() if relacao.find(f'ans:{tag}', NS) is not None else "") 
                for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']}
        
        itens_ret = []
        for item in relacao.findall('.//ans:detalhesGuia', NS):
            p_el = item.find('.//ans:procedimento', NS)
            v_inf = item.find('.//ans:valorInformado', NS).text if item.find('.//ans:valorInformado', NS) is not None else "0.00"
            desc_ret = p_el.find('ans:descricaoProcedimento', NS).text if p_el is not None and p_el.find('ans:descricaoProcedimento', NS) is not None else None
            
            glosas = [{'valor': g.find('ans:valorGlosa', NS).text, 'tipo': g.find('ans:tipoGlosa', NS).text} 
                      for g in item.findall('.//ans:relacaoGlosa', NS)]

            itens_ret.append({
                'cod': p_el.find('ans:codigoProcedimento', NS).text if p_el is not None else "",
                'desc': desc_ret, 'v_inf': f"{float(v_inf):.2f}",
                'v_proc': item.find('.//ans:valorProcessado', NS).text if item.find('.//ans:valorProcessado', NS) is not None else v_inf,
                'v_lib': item.find('.//ans:valorLiberado', NS).text if item.find('.//ans:valorLiberado', NS) is not None else "0.00",
                'glosas': glosas, 'usado': False
            })
        
        dados = {'meta': meta, 'itens': itens_ret}
        if n_guia_prest is not None: mapa_retorno[f"GUIA_{n_guia_prest.text.strip()}"] = dados
        if n_guia_oper is not None: mapa_retorno[f"OPER_{n_guia_oper.text.strip()}"] = dados
        if carteira is not None: mapa_retorno[f"CART_{carteira.text.strip()}"] = dados
        if senha is not None: mapa_retorno[f"SENH_{senha.text.strip()}"] = dados

    # 2. CONSTRUÇÃO DO NOVO XML
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS')
    
    if (cab := root_ret.find('ans:cabecalho', NS)) is not None: novo_root.append(cab)
    op_para_prest = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativosRetorno')
    demonstrativo = ET.SubElement(demons_ret, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativoAnaliseConta')
    
    if (cb_dem := root_ret.find('.//ans:cabecalhoDemonstrativo', NS)) is not None: demonstrativo.append(cb_dem)
    if (dd_pr := root_ret.find('.//ans:dadosPrestador', NS)) is not None: demonstrativo.append(dd_pr)

    dados_conta = ET.SubElement(demonstrativo, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosConta')
    protocolo = ET.SubElement(dados_conta, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosProtocolo')
    
    for tag in ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']:
        el = root_ret.find(f'.//ans:{tag}', NS)
        ET.SubElement(protocolo, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{tag}').text = el.text if el is not None else ""

    total_inf_final, total_lib_final, processadas = 0.0, 0.0, set()

    # 3. PROCESSAMENTO
    for elemento in root_env.findall('.//*', NS):
        tag_name = elemento.tag.split('}')[-1]
        if 'guia' not in tag_name.lower() or any(x in tag_name.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_env = elemento.find('.//ans:numeroGuiaPrestador', NS).text.strip() if elemento.find('.//ans:numeroGuiaPrestador', NS) is not None else ""
        
        # FILTRO DE SELEÇÃO: Se passou uma lista e a guia não está nela, pula.
        if guias_selecionadas is not None and n_guia_env not in guias_selecionadas:
            continue
        if n_guia_env in processadas: continue

        # Identificação
        n_oper_env = elemento.find('.//ans:numeroGuiaOperadora', NS).text.strip() if elemento.find('.//ans:numeroGuiaOperadora', NS) is not None else ""
        cart_env = elemento.find('.//ans:numeroCarteira', NS).text.strip() if elemento.find('.//ans:numeroCarteira', NS) is not None else ""
        senha_el = elemento.find('.//ans:senha', NS) or elemento.find('.//ans:dadosAutorizacao/ans:senha', NS)
        senha_env = senha_el.text.strip() if senha_el is not None and senha_el.text else ""

        res_guia = (mapa_retorno.get(f"GUIA_{n_guia_env}") or mapa_retorno.get(f"OPER_{n_oper_env}") or 
                    mapa_retorno.get(f"SENH_{senha_env}") or mapa_retorno.get(f"CART_{cart_env}"))
        
        if not res_guia: continue
        processadas.add(n_guia_env)

        m, itens_ret = res_guia['meta'], res_guia['itens']
        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = n_oper_env if n_oper_env else m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = senha_env if senha_env else m.get('senha', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = cart_env

        # Datas
        d_ini = m.get('dataInicioFat', "")
        if tag_name == 'guiaResumoInternacao' and is_amazonia:
            d_ini_env = elemento.find('.//ans:dataInicioFaturamento', NS)
            d_ini = d_ini_env.text if d_ini_env is not None else d_ini

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataInicioFat').text = d_ini
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaInicioFat').text = "00:00:00"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataFimFat').text = d_ini
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaFimFat').text = "00:00:00"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}situacaoGuia').text = m.get('situacaoGuia', "")

        t_g_inf, t_g_lib = 0.0, 0.0
        itens_env = elemento.findall('.//ans:procedimento', NS) if tag_name == 'guiaConsulta' else (elemento.findall('.//ans:procedimentoExecutado', NS) + elemento.findall('.//ans:despesa', NS))

        for idx, i_env in enumerate(itens_env):
            # Lógica simplificada de extração de valores do envio
            v_total_el = i_env.find('.//ans:valorTotal', NS) or i_env.find('.//ans:valorProcedimento', NS)
            v_env_s = f"{float(v_total_el.text):.2f}" if (v_total_el is not None and v_total_el.text) else "0.00"
            
            match = next((it for it in itens_ret if not it['usado'] and it['v_inf'] == v_env_s), None)
            if match: match['usado'] = True

            v_inf = match['v_inf'] if match else v_env_s
            v_lib = match['v_lib'] if match else "0.00"

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(idx + 1)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = d_ini
            
            p_tag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            p_env = i_env.find('.//ans:procedimento', NS) or i_env
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = p_env.find('.//ans:codigoTabela', NS).text if p_env.find('.//ans:codigoTabela', NS) is not None else "00"
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = p_env.find('.//ans:codigoProcedimento', NS).text if p_env.find('.//ans:codigoProcedimento', NS) is not None else "00"
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = match['desc'] if (match and match['desc']) else "PROCEDIMENTO"
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = "1.00"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            # Glosas
            for g in (match['glosas'] if match else []):
                t = g['tipo']
                if is_amazonia:
                    t = '1705' if t in CODIGOS_GLOSA_PARA_1705 else ('1801' if t in CODIGOS_GLOSA_PADRAO else t)
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = g['valor']
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = t

            t_g_inf += float(v_inf); t_g_lib += float(v_lib)

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        
        total_inf_final += t_g_inf; total_lib_final += t_g_lib

    # 4. TOTAIS FINAIS RECALCULADOS
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_final - total_lib_final):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    xml_str = ET.tostring(novo_root, encoding='ISO-8859-1')
    return minidom.parseString(xml_str).toprettyxml(indent="  ", encoding='ISO-8859-1')
