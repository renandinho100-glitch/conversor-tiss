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

    # 1. MAPEAMENTO DO RETORNO ORGANIZADO POR GUIA E POSIÇÃO
    mapa_guias_retorno = {}
    mapa_cabecalho_guia = {} 
    
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia_elem = relacao.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_elem is None: continue
        n_guia = n_guia_elem.text.strip()
        
        # Metadados da guia
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        mapa_cabecalho_guia[n_guia] = meta

        # Lista ordenada de itens para permitir a busca por "vizinhança"
        itens_ret_lista = []
        for item in relacao.findall('.//ans:detalhesGuia', ns):
            p_elem = item.find('.//ans:procedimento', ns)
            v_inf_ret = f"{float(item.find('.//ans:valorInformado', ns).text):.2f}"
            
            glosas = []
            for g_rel in item.findall('.//ans:relacaoGlosa', ns):
                glosas.append({
                    'valor': g_rel.find('ans:valorGlosa', ns).text,
                    'tipo': g_rel.find('ans:tipoGlosa', ns).text
                })

            itens_ret_lista.append({
                'seq_ret': item.find('ans:sequencialItem', ns).text if item.find('ans:sequencialItem', ns) is not None else "",
                'cod_ret': p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else "",
                'v_inf': v_inf_ret,
                'v_proc': item.find('.//ans:valorProcessado', ns).text if item.find('.//ans:valorProcessado', ns) is not None else v_inf_ret,
                'v_lib': item.find('.//ans:valorLiberado', ns).text,
                'glosas': glosas,
                'usado': False # Flag para não casar o mesmo item do retorno duas vezes
            })
        mapa_guias_retorno[n_guia] = itens_ret_lista

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

    total_inf_geral, total_lib_geral, processadas = 0.0, 0.0, set()

    # 3. PROCESSAMENTO COM REGRA DE VIZINHANÇA
    for elemento in root_env.findall('.//*', ns):
        tag_name = elemento.tag.split('}')[-1]
        if 'guia' not in tag_name.lower() or any(x in tag_name.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_el = elemento.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_el is None: continue
        n_guia_env = n_guia_el.text.strip()
        
        if n_guia_env in processadas or n_guia_env not in mapa_guias_retorno: continue
        processadas.add(n_guia_env)

        m = mapa_cabecalho_guia[n_guia_env]
        itens_ret_disponiveis = mapa_guias_retorno[n_guia_env]
        
        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = m['numeroGuiaOperadora']
        
        s_el = elemento.find('.//ans:senha', ns) or elemento.find('.//ans:dadosAutorizacao/ans:senha', ns)
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = s_el.text.strip() if s_el is not None and s_el.text else m.get('senha', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = elemento.find('.//ans:numeroCarteira', ns).text if elemento.find('.//ans:numeroCarteira', ns) is not None else ""
        
        for t in ['dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            ET.SubElement(rel_guia, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{t}').text = m.get(t, "")

        t_g_inf, t_g_lib = 0.0, 0.0
        itens_env = elemento.findall('.//ans:procedimentoExecutado', ns) + elemento.findall('.//ans:despesa', ns)
        
        for idx_env, item_env in enumerate(itens_env):
            servico = item_env.find('.//ans:servicosExecutados', ns) if item_env.tag.endswith('despesa') else item_env
            proc_dados = servico.find('.//ans:procedimento', ns) if servico.find('.//ans:procedimento', ns) is not None else servico
            
            s_env = item_env.find('ans:sequencialItem', ns).text if item_env.find('ans:sequencialItem', ns) is not None else ""
            cod_env = proc_dados.find('.//ans:codigoProcedimento', ns).text
            v_env_str = f"{float(servico.find('.//ans:valorTotal', ns).text):.2f}"
            
            res = None
            if is_amazonia:
                # REGRA DE MARGEM: Procurar nos itens do retorno entre idx_env-5 e idx_env+5
                inicio_janela = max(0, idx_env - 5)
                fim_janela = min(len(itens_ret_disponiveis), idx_env + 6)
                
                # 1ª Tentativa na Janela: Valor + Sequencial ou Valor + Código
                for i in range(inicio_janela, fim_janela):
                    it = itens_ret_disponiveis[i]
                    if not it['usado'] and it['v_inf'] == v_env_str and (it['seq_ret'] == s_env or it['cod_ret'] == cod_env):
                        res = it
                        it['usado'] = True
                        break
                
                # 2ª Tentativa na Janela: Apenas Valor
                if not res:
                    for i in range(inicio_janela, fim_janela):
                        it = itens_ret_disponiveis[i]
                        if not it['usado'] and it['v_inf'] == v_env_str:
                            res = it
                            it['usado'] = True
                            break

                # 3ª Tentativa: Busca Global na Guia (se ainda não achou na janela)
                if not res:
                    for it in itens_ret_disponiveis:
                        if not it['usado'] and it['v_inf'] == v_env_str and it['cod_ret'] == cod_env:
                            res = it
                            it['usado'] = True
                            break
            else:
                # Lógica padrão para outros convênios
                for it in itens_ret_disponiveis:
                    if not it['usado'] and it['v_inf'] == v_env_str and it['cod_ret'] == cod_env:
                        res = it
                        it['usado'] = True
                        break

            v_inf = res['v_inf'] if res else v_env_str
            v_proc = res['v_proc'] if res else v_env_str
            v_lib = res['v_lib'] if res else v_env_str
            glosas = res['glosas'] if res else []

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = s_env if s_env else str(idx_env + 1)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = servico.find('.//ans:dataExecucao', ns).text
            
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = proc_dados.find('.//ans:codigoTabela', ns).text
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = cod_env
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = proc_dados.find('.//ans:descricaoProcedimento', ns).text
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = servico.find('.//ans:quantidadeExecutada', ns).text
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_proc
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            tipos_adicionados = set()
            for g in glosas:
                tipo = g['tipo']
                if is_amazonia:
                    if tipo in codigos_glosa_para_1705: tipo = '1705'
                    elif tipo in codigos_glosa_padrao: tipo = '1801'
                
                if tipo not in tipos_adicionados:
                    rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = g['valor']
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = tipo
                    tipos_adicionados.add(tipo)

            t_g_inf += float(v_inf)
            t_g_lib += float(v_lib)

        # Totais da Guia e Finais permanecem com a lógica de soma corrigida
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        total_inf_geral += t_g_inf
        total_lib_geral += t_g_lib

    # Finalização dos totais de protocolo e geral (como nas versões anteriores)
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_geral - total_lib_geral):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    return minidom.parseString(ET.tostring(novo_root, 'iso-8859-1')).toprettyxml(indent="  ", encoding='ISO-8859-1')
