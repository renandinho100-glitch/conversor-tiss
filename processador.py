import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import BytesIO

# --- CONFIGURAÇÕES TÉCNICAS TISS ---
NS = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
CODIGOS_GLOSA_PARA_1705 = ['1799', '9918', '1899']
CODIGOS_GLOSA_PADRAO = ['1099', '1199', '1999', '3099']

def extrair_metadados(retorno_file):
    """
    Lê o arquivo de retorno e extrai o número do lote e a lista de guias 
    para alimentar os checkboxes no site.
    """
    try:
        tree = ET.parse(retorno_file)
        root = tree.getroot()
        lote_el = root.find('.//ans:numeroLotePrestador', NS)
        lote_id = lote_el.text if lote_el is not None else "Lote_Unico"
        
        guias = []
        for rel in root.findall('.//ans:relacaoGuias', NS):
            g_el = rel.find('.//ans:numeroGuiaPrestador', NS)
            if g_el is not None and g_el.text:
                guias.append(g_el.text.strip())
        
        return lote_id, sorted(list(set(guias)))
    except Exception:
        return "Erro", []

def processar_xmls(envio_file, retorno_file, guias_selecionadas=None):
    """
    Gera o XML final cruzando Envio e Retorno.
    Inclui regras de datas para SADT e mapeamento para operadora Amazônia.
    """
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    ET.register_namespace('xsi', "http://www.w3.org/2001/XMLSchema-instance")

    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}"

    # Identificação da Operadora (Amazônia = 419052)
    reg_ans_el = root_ret.find('.//ans:registroANS', NS)
    is_amazonia = reg_ans_el is not None and reg_ans_el.text == '419052'

    # 1. MAPEAMENTO DO RETORNO (Dicionário para busca rápida)
    mapa_retorno = {}
    for relacao in root_ret.findall('.//ans:relacaoGuias', NS):
        n_guia_prest = relacao.find('.//ans:numeroGuiaPrestador', NS)
        
        # Coleta metadados da guia
        meta = {tag: (relacao.find(f'ans:{tag}', NS).text.strip() if relacao.find(f'ans:{tag}', NS) is not None else "") 
                for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']}
        
        # Coleta itens processados (glosas e valores)
        itens_ret = []
        for item in relacao.findall('.//ans:detalhesGuia', NS):
            p_el = item.find('.//ans:procedimento', NS)
            v_inf = item.find('.//ans:valorInformado', NS).text if item.find('.//ans:valorInformado', NS) is not None else "0.00"
            desc = p_el.find('ans:descricaoProcedimento', NS).text if p_el is not None and p_el.find('ans:descricaoProcedimento', NS) is not None else "PROCEDIMENTO"
            
            glosas = [{'valor': g.find('ans:valorGlosa', NS).text, 'tipo': g.find('ans:tipoGlosa', NS).text} 
                      for g in item.findall('.//ans:relacaoGlosa', NS)]

            itens_ret.append({
                'cod': p_el.find('ans:codigoProcedimento', NS).text if p_el is not None else "",
                'desc': desc,
                'v_inf': f"{float(v_inf):.2f}",
                'v_proc': item.find('.//ans:valorProcessado', NS).text if item.find('.//ans:valorProcessado', NS) is not None else v_inf,
                'v_lib': item.find('.//ans:valorLiberado', NS).text if item.find('.//ans:valorLiberado', NS) is not None else "0.00",
                'glosas': glosas,
                'usado': False
            })
        
        if n_guia_prest is not None:
            mapa_retorno[n_guia_prest.text.strip()] = {'meta': meta, 'itens': itens_ret}

    # 2. ESTRUTURA DO NOVO XML
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

    # 3. PROCESSAMENTO DAS GUIAS DO ENVIO
    for elemento in root_env.findall('.//*', NS):
        tag_full = elemento.tag.split('}')[-1]
        if 'guia' not in tag_full.lower() or any(x in tag_full.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_env = elemento.find('.//ans:numeroGuiaPrestador', NS).text.strip() if elemento.find('.//ans:numeroGuiaPrestador', NS) is not None else ""
        
        # Filtros: Seleção do usuário e duplicidade
        if guias_selecionadas is not None and n_guia_env not in guias_selecionadas: continue
        if n_guia_env in processadas or n_guia_env not in mapa_retorno: continue
        
        processadas.add(n_guia_env)
        guia_info = mapa_retorno[n_guia_env]
        m, itens_ret = guia_info['meta'], guia_info['itens']

        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = m['senha']
        
        cart_env = elemento.find('.//ans:numeroCarteira', NS)
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = cart_env.text.strip() if cart_env is not None else ""

        # --- LÓGICA DE DATAS (SADT E INTERNAÇÃO) ---
        data_padrao = m.get('dataInicioFat', "")
        if tag_full == 'guiaSP-SADT' or tag_full == 'guiaResumoInternacao':
            # Tenta pegar a data de execução ou atendimento do envio caso a do retorno esteja vazia
            dt_env = elemento.find('.//ans:dataAtendimento', NS) or elemento.find('.//ans:dataExecucao', NS) or elemento.find('.//ans:dataInicioFaturamento', NS)
            if dt_env is not None and not data_padrao:
                data_padrao = dt_env.text

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataInicioFat').text = data_padrao
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaInicioFat').text = m.get('horaInicioFat', "00:00:00")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataFimFat').text = m.get('dataFimFat', data_padrao)
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaFimFat').text = m.get('horaFimFat', "00:00:00")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}situacaoGuia').text = m.get('situacaoGuia', "")

        # Processamento de Itens
        t_g_inf, t_g_lib = 0.0, 0.0
        itens_env = elemento.findall('.//ans:procedimento', NS) if tag_full == 'guiaConsulta' else (elemento.findall('.//ans:procedimentoExecutado', NS) + elemento.findall('.//ans:despesa', NS))

        for idx, i_env in enumerate(itens_env):
            v_total_el = i_env.find('.//ans:valorTotal', NS) or i_env.find('.//ans:valorProcedimento', NS)
            v_env_s = f"{float(v_total_el.text):.2f}" if (v_total_el is not None and v_total_el.text) else "0.00"
            
            # Tenta dar match com o retorno pelo valor
            match = next((it for it in itens_ret if not it['usado'] and it['v_inf'] == v_env_s), None)
            if match: match['usado'] = True

            v_inf = match['v_inf'] if match else v_env_s
            v_lib = match['v_lib'] if match else "0.00"

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(idx + 1)
            
            # Data do item (essencial para SADT)
            dt_item_el = i_env.find('.//ans:dataExecucao', NS) or i_env.find('.//ans:dataRealizacao', NS)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = dt_item_el.text if dt_item_el is not None else data_padrao
            
            p_tag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            p_env = i_env.find('.//ans:procedimento', NS) or i_env
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = p_env.find('.//ans:codigoTabela', NS).text if p_env.find('.//ans:codigoTabela', NS) is not None else "00"
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = p_env.find('.//ans:codigoProcedimento', NS).text if p_env.find('.//ans:codigoProcedimento', NS) is not None else "00"
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = match['desc'] if match else "PROCEDIMENTO"
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = "1.00"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = match['v_proc'] if match else v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            # Glosas com regra Amazônia
            for g in (match['glosas'] if match else []):
                t = g['tipo']
                if is_amazonia:
                    t = '1705' if t in CODIGOS_GLOSA_PARA_1705 else ('1801' if t in CODIGOS_GLOSA_PADRAO else t)
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = g['valor']
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = t

            t_g_inf += float(v_inf); t_g_lib += float(v_lib)

        # Totais da Guia
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        
        total_inf_final += t_g_inf; total_lib_final += t_g_lib

    # 4. TOTAIS DO PROTOCOLO E GERAL
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_final:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_final - total_lib_final):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    xml_str = ET.tostring(novo_root, encoding='ISO-8859-1')
    return minidom.parseString(xml_str).toprettyxml(indent="  ", encoding='ISO-8859-1')
