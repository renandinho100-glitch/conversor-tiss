import xml.etree.ElementTree as ET
from io import BytesIO
from collections import deque
from xml.dom import minidom
import re

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    ET.register_namespace('xsi', "http://www.w3.org/2001/XMLSchema-instance")
    
    codigos_glosa_para_1705 = ['1799', '9918', '1899']
    codigos_glosa_padrao = ['1099', '1199', '1999', '3099']

    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}"

    reg_ans_el = root_ret.find('.//ans:registroANS', ns)
    is_amazonia = reg_ans_el is not None and reg_ans_el.text == '419052'

    # 1. MAPEAMENTO DO RETORNO (Criação de índices para busca rápida)
    mapa_por_guia = {}
    mapa_por_carteira = {}
    mapa_por_senha = {}
    
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia_el = relacao.find('.//ans:numeroGuiaPrestador', ns)
        carteira_el = relacao.find('.//ans:numeroCarteira', ns)
        senha_el = relacao.find('.//ans:senha', ns)
        
        n_guia = n_guia_el.text.strip() if n_guia_el is not None else None
        carteira = carteira_el.text.strip() if carteira_el is not None else None
        senha = senha_el.text.strip() if senha_el is not None else None
        
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        
        # Itens do retorno para esta guia
        itens_ret_lista = []
        for item in relacao.findall('.//ans:detalhesGuia', ns):
            p_elem = item.find('.//ans:procedimento', ns)
            v_inf_raw = item.find('.//ans:valorInformado', ns).text
            
            glosas = []
            for g_rel in item.findall('.//ans:relacaoGlosa', ns):
                glosas.append({
                    'valor': g_rel.find('ans:valorGlosa', ns).text,
                    'tipo': g_rel.find('ans:tipoGlosa', ns).text
                })

            itens_ret_lista.append({
                'cod_ret': p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else "",
                'v_inf': f"{float(v_inf_raw):.2f}",
                'v_proc': item.find('.//ans:valorProcessado', ns).text,
                'v_lib': item.find('.//ans:valorLiberado', ns).text,
                'glosas': glosas,
                'usado': False 
            })
        
        dados_guia = {'meta': meta, 'itens': itens_ret_lista}
        
        if n_guia: mapa_por_guia[n_guia] = dados_guia
        if carteira: mapa_por_carteira[carteira] = dados_guia
        if senha: mapa_por_senha[senha] = dados_guia

    # 2. ESTRUTURA DO NOVO XML
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS', {
        '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation': 'http://www.ans.gov.br/padroes/tiss/schemas http://www.ans.gov.br/padroes/tiss/schemas/tissV4_01_00.xsd'
    })
    
    if (cab := root_ret.find('ans:cabecalho', ns)) is not None: novo_root.append(cab)
    op_para_prest = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativosRetorno')
    demonstrativo = ET.SubElement(demons_ret, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativoAnaliseConta')
    
    if (cb_dem := root_ret.find('.//ans:cabecalhoDemonstrativo', ns)) is not None: demonstrativo.append(cb_dem)
    if (dd_pr := root_ret.find('.//ans:dadosPrestador', ns)) is not None: demonstrativo.append(dd_pr)

    dados_conta = ET.SubElement(demonstrativo, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosConta')
    protocolo = ET.SubElement(dados_conta, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosProtocolo')
    
    for tag in ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']:
        el = root_ret.find(f'.//ans:{tag}', ns)
        ET.SubElement(protocolo, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{tag}').text = el.text if el is not None else ""

    total_inf_geral, total_lib_geral, processadas_guias = 0.0, 0.0, set()

    # 3. PROCESSAMENTO PRIORIZANDO O ENVIO
    for elemento in root_env.findall('.//*', ns):
        tag_name = elemento.tag.split('}')[-1]
        if 'guia' not in tag_name.lower() or any(x in tag_name.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_el = elemento.find('.//ans:numeroGuiaPrestador', ns)
        carteira_el = elemento.find('.//ans:numeroCarteira', ns)
        senha_el = elemento.find('.//ans:senha', ns) or elemento.find('.//ans:dadosAutorizacao/ans:senha', ns)

        n_guia_env = n_guia_el.text.strip() if n_guia_el is not None else ""
        carteira_env = carteira_el.text.strip() if carteira_el is not None else ""
        senha_env = senha_el.text.strip() if senha_el is not None else ""

        if n_guia_env in processadas_guias: continue

        # HIERARQUIA DE BUSCA NO RETORNO
        guia_retorno = mapa_por_guia.get(n_guia_env) or mapa_por_carteira.get(carteira_env) or mapa_por_senha.get(senha_env)
        
        if not guia_retorno: continue
        processadas_guias.add(n_guia_env)

        m = guia_retorno['meta']
        itens_ret_disponiveis = guia_retorno['itens']
        
        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = senha_env if senha_env else m.get('senha', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = carteira_env
        
        # Regras de Data e Hora
        data_ref = m.get('dataInicioFat', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataInicioFat').text = data_ref
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaInicioFat').text = "00:00:00"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataFimFat').text = data_ref
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaFimFat').text = "00:00:00"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}situacaoGuia').text = m.get('situacaoGuia', "")

        t_g_inf, t_g_lib = 0.0, 0.0
        
        # Itens do Envio
        if tag_name == 'guiaConsulta':
            itens_env = elemento.findall('.//ans:procedimento', ns)
        else:
            itens_env = elemento.findall('.//ans:procedimentoExecutado', ns) + elemento.findall('.//ans:despesa', ns)
        
        for idx_env, item_env in enumerate(itens_env):
            if tag_name == 'guiaConsulta':
                proc_dados = item_env
                v_total_el = item_env.find('.//ans:valorProcedimento', ns)
                dt_item = elemento.find('.//ans:dataAtendimento', ns).text if elemento.find('.//ans:dataAtendimento', ns) is not None else data_ref
            else:
                servico = item_env.find('.//ans:servicosExecutados', ns) if item_env.tag.endswith('despesa') else item_env
                proc_dados = servico.find('.//ans:procedimento', ns) if servico.find('.//ans:procedimento', ns) is not None else servico
                v_total_el = servico.find('.//ans:valorTotal', ns)
                dt_item = servico.find('.//ans:dataExecucao', ns).text if servico.find('.//ans:dataExecucao', ns) is not None else data_ref

            v_env_str = f"{float(v_total_el.text):.2f}" if (v_total_el is not None and v_total_el.text) else "0.00"
            
            # Tentar parear item pelo valor
            res = None
            for it in itens_ret_disponiveis:
                if not it['usado'] and it['v_inf'] == v_env_str:
                    res = it
                    it['usado'] = True
                    break

            v_inf = res['v_inf'] if res else v_env_str
            v_proc = res['v_proc'] if res else v_env_str
            v_lib = res['v_lib'] if res else v_env_str
            glosas_originais = res['glosas'] if res else []

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(idx_env + 1)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = dt_item
            
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = proc_dados.find('.//ans:codigoTabela', ns).text
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = proc_dados.find('.//ans:codigoProcedimento', ns).text
            
            desc_el = proc_dados.find('.//ans:descricaoProcedimento', ns)
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = desc_el.text if desc_el is not None else ""
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = "1.00"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_proc
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            # Regras de Glosa (Anti-duplicidade)
            tipos_add = set()
            for g in glosas_originais:
                tipo = g['tipo']
                if is_amazonia:
                    if tipo in codigos_glosa_para_1705: tipo = '1705'
                    elif tipo in codigos_glosa_padrao: tipo = '1801'
                if tipo not in tipos_add:
                    rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = g['valor']
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = tipo
                    tipos_add.add(tipo)

            t_g_inf += float(v_inf)
            t_g_lib += float(v_lib)

        # Totais da Guia
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        
        total_inf_geral += t_g_inf
        total_lib_geral += t_g_lib

    # Totais Finais
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_geral - total_lib_geral):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    return minidom.parseString(ET.tostring(novo_root, 'iso-8859-1')).toprettyxml(indent="  ", encoding='ISO-8859-1')
