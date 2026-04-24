import xml.etree.ElementTree as ET
from io import BytesIO
from xml.dom import minidom

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
    reg_ans_texto = reg_ans_el.text if reg_ans_el is not None else ""
    
    is_amazonia = reg_ans_texto == '419052'
    is_unimed = reg_ans_texto == '303976'

    # 1. MAPEAMENTO DO RETORNO
    mapa_retorno = {}
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia_prest_ret = relacao.find('.//ans:numeroGuiaPrestador', ns)
        n_guia_oper_ret = relacao.find('.//ans:numeroGuiaOperadora', ns)
        carteira_ret = relacao.find('.//ans:numeroCarteira', ns)
        senha_ret = relacao.find('.//ans:senha', ns)
        
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        
        itens_ret_lista = []
        for item in relacao.findall('.//ans:detalhesGuia', ns):
            p_elem = item.find('.//ans:procedimento', ns)
            v_inf_raw = item.find('.//ans:valorInformado', ns).text if item.find('.//ans:valorInformado', ns) is not None else "0.00"
            desc_ret = p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None and p_elem.find('ans:descricaoProcedimento', ns) is not None else None

            glosas = []
            for g_rel in item.findall('.//ans:relacaoGlosa', ns):
                glosas.append({
                    'valor': g_rel.find('ans:valorGlosa', ns).text,
                    'tipo': g_rel.find('ans:tipoGlosa', ns).text
                })

            itens_ret_lista.append({
                'cod_ret': p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else "",
                'desc_ret': desc_ret,
                'v_inf': f"{float(v_inf_raw):.2f}",
                'v_proc': item.find('.//ans:valorProcessado', ns).text if item.find('.//ans:valorProcessado', ns) is not None else f"{float(v_inf_raw):.2f}",
                'v_lib': item.find('.//ans:valorLiberado', ns).text if item.find('.//ans:valorLiberado', ns) is not None else "0.00",
                'glosas': glosas,
                'usado': False 
            })
        
        dados_guia = {'meta': meta, 'itens': itens_ret_lista}
        if n_guia_prest_ret is not None: mapa_retorno[f"GUIA_{n_guia_prest_ret.text.strip()}"] = dados_guia
        if n_guia_oper_ret is not None: mapa_retorno[f"OPER_{n_guia_oper_ret.text.strip()}"] = dados_guia
        if carteira_ret is not None: mapa_retorno[f"CART_{carteira_ret.text.strip()}"] = dados_guia
        if senha_ret is not None: mapa_retorno[f"SENH_{senha_ret.text.strip()}"] = dados_guia

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

    # 3. PROCESSAMENTO
    for elemento in root_env.findall('.//*', ns):
        tag_name = elemento.tag.split('}')[-1]
        if 'guia' not in tag_name.lower() or any(x in tag_name.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_prest_env = elemento.find('.//ans:numeroGuiaPrestador', ns).text.strip() if elemento.find('.//ans:numeroGuiaPrestador', ns) is not None else ""
        n_guia_oper_env = elemento.find('.//ans:numeroGuiaOperadora', ns).text.strip() if elemento.find('.//ans:numeroGuiaOperadora', ns) is not None else ""
        carteira_env = elemento.find('.//ans:numeroCarteira', ns).text.strip() if elemento.find('.//ans:numeroCarteira', ns) is not None else ""
        senha_el = elemento.find('.//ans:senha', ns) or elemento.find('.//ans:dadosAutorizacao/ans:senha', ns)
        senha_env = senha_el.text.strip() if senha_el is not None and senha_el.text else ""

        if n_guia_prest_env in processadas_guias: continue

        guia_retorno = (mapa_retorno.get(f"GUIA_{n_guia_prest_env}") or 
                        mapa_retorno.get(f"GUIA_{n_guia_oper_env}") or
                        mapa_retorno.get(f"OPER_{n_guia_oper_env}") or
                        mapa_retorno.get(f"SENH_{senha_env}") or
                        mapa_retorno.get(f"CART_{carteira_env}"))
        
        if not guia_retorno: continue
        processadas_guias.add(n_guia_prest_env)

        m = guia_retorno['meta']
        itens_ret_disponiveis = guia_retorno['itens']
        
        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_prest_env
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = n_guia_oper_env if n_guia_oper_env else m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = senha_env if senha_env else m.get('senha', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = carteira_env
        
        # --- LÓGICA DE DATAS (AJUSTE SADT E INTERNAÇÃO) ---
        if tag_name in ['guiaResumoInternacao', 'guiaSP-SADT']:
            d_ini = elemento.find('.//ans:dataInicioFaturamento', ns) or elemento.find('.//ans:dataAtendimento', ns) or elemento.find('.//ans:dataExecucao', ns)
            h_ini = elemento.find('.//ans:horaInicioFaturamento', ns) or elemento.find('.//ans:horaAtendimento', ns)
            d_fim = elemento.find('.//ans:dataFinalFaturamento', ns) or elemento.find('.//ans:dataFimFaturamento', ns)
            h_fim = elemento.find('.//ans:horaFinalFaturamento', ns) or elemento.find('.//ans:horaFimFaturamento', ns)
            
            data_ini_val = d_ini.text if d_ini is not None else m.get('dataInicioFat', "")
            hora_ini_val = h_ini.text if h_ini is not None else m.get('horaInicioFat', "00:00:00")
            data_fim_val = d_fim.text if d_fim is not None else m.get('dataFimFat', data_ini_val)
            hora_fim_val = h_fim.text if h_fim is not None else m.get('horaFimFat', "00:00:00")
        else:
            data_ini_val = m.get('dataInicioFat', "")
            data_fim_val = m.get('dataInicioFat', "")
            hora_ini_val = "00:00:00"
            hora_fim_val = "00:00:00"

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataInicioFat').text = data_ini_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaInicioFat').text = hora_ini_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataFimFat').text = data_fim_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaFimFat').text = hora_fim_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}situacaoGuia').text = m.get('situacaoGuia', "")

        t_g_inf, t_g_lib = 0.0, 0.0
        
        # Itens do Envio
        if tag_name == 'guiaConsulta':
            itens_env = elemento.findall('.//ans:procedimento', ns)
        else:
            itens_env = elemento.findall('.//ans:procedimentoExecutado', ns) + elemento.findall('.//ans:despesa', ns)
        
        for idx_env, item_env in enumerate(itens_env):
            if tag_name == 'guiaConsulta':
                v_total_el = item_env.find('.//ans:valorProcedimento', ns)
                dt_item = elemento.find('.//ans:dataAtendimento', ns).text if elemento.find('.//ans:dataAtendimento', ns) is not None else data_ini_val
                proc_env = item_env
            else:
                servico = item_env.find('.//ans:servicosExecutados', ns) if item_env.tag.endswith('despesa') else item_env
                v_total_el = servico.find('.//ans:valorTotal', ns)
                dt_item_el = servico.find('.//ans:dataExecucao', ns) or servico.find('.//ans:dataRealizacao', ns)
                dt_item = dt_item_el.text if dt_item_el is not None else data_ini_val
                proc_env = servico.find('.//ans:procedimento', ns) if servico.find('.//ans:procedimento', ns) is not None else servico

            v_env_str = f"{float(v_total_el.text):.2f}" if (v_total_el is not None and v_total_el.text) else "0.00"
            
            res = None
            for it in itens_ret_disponiveis:
                if not it['usado'] and it['v_inf'] == v_env_str:
                    res = it
                    it['usado'] = True
                    break

            desc_final = ""
            if res and res['desc_ret']:
                desc_final = res['desc_ret']
            elif proc_env.find('.//ans:descricaoProcedimento', ns) is not None:
                desc_final = proc_env.find('.//ans:descricaoProcedimento', ns).text

            v_inf = res['v_inf'] if res else v_env_str
            v_proc = res['v_proc'] if res else v_env_str
            v_lib = res['v_lib'] if res else v_env_str
            glosas_originais = res['glosas'] if res else []

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(idx_env + 1)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = dt_item
            
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = proc_env.find('.//ans:codigoTabela', ns).text if proc_env.find('.//ans:codigoTabela', ns) is not None else "00"
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = proc_env.find('.//ans:codigoProcedimento', ns).text if proc_env.find('.//ans:codigoProcedimento', ns) is not None else "00"
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = desc_final
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = "1.00"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_proc
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            tipos_add = set()
            for g in glosas_originais:
                tipo = g['tipo']
                if is_amazonia:
                    if tipo in codigos_glosa_para_1705: tipo = '1705'
                    elif tipo in codigos_glosa_padrao: tipo = '1801'
                elif is_unimed:
                    if tipo in codigos_glosa_padrao: tipo = '1801'
                
                if tipo not in tipos_add:
                    rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = g['valor']
                    ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = tipo
                    tipos_add.add(tipo)

            t_g_inf += float(v_inf)
            t_g_lib += float(v_lib)

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        
        total_inf_geral += t_g_inf
        total_lib_geral += t_g_lib

    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_geral - total_lib_geral):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    xml_final = ET.tostring(novo_root, 'iso-8859-1')
    return minidom.parseString(xml_final).toprettyxml(indent="  ", encoding='ISO-8859-1')
