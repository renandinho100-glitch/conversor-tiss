import xml.etree.ElementTree as ET
from io import BytesIO
from xml.dom import minidom

def limpar_numero(texto):
    """Remove zeros à esquerda e espaços para garantir a comparação numérica entre Envio e Retorno."""
    if texto:
        return texto.strip().lstrip('0')
    return ""

def limpar_hora(hora_texto):
    """Garante que a hora retorne estritamente no formato HH:MM:SS, removendo milissegundos e fuso."""
    if hora_texto:
        hora_limpa = hora_texto.strip()
        # Se contiver fuso ou milissegundos, pega apenas os primeiros 8 caracteres (HH:MM:SS)
        return hora_limpa[:8]
    return "00:00:00"

def processar_xmls(envio_file, retorno_file):
    # Namespaces padrão TISS
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    ET.register_namespace('xsi', "http://www.w3.org/2001/XMLSchema-instance")
    
    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}"

    # Identificação do Convênio
    reg_ans_el = root_ret.find('.//ans:registroANS', ns)
    reg_ans_texto = reg_ans_el.text if reg_ans_el is not None else ""
    
    # Flags de Convênio
    is_amazonia = reg_ans_texto == '419052'
    is_casf = reg_ans_texto == '358754'
    
    # Agrupador de regras especiais (Amazônia e CASF)
    aplicar_regra_especial = is_amazonia or is_casf

    # 1. MAPEAMENTO DO RETORNO (Suporta múltiplas ocorrências da mesma guia com períodos diferentes)
    mapa_retorno = {}

    def adicionar_ao_mapa(chave, dados):
        if chave not in mapa_retorno:
            mapa_retorno[chave] = []
        mapa_retorno[chave].append(dados)

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
            v_lib_raw = item.find('.//ans:valorLiberado', ns).text if item.find('.//ans:valorLiberado', ns) is not None else "0.00"
            
            glosa_el = item.find('.//ans:relacaoGlosa/ans:tipoGlosa', ns)
            glosa_original = glosa_el.text.strip() if (glosa_el is not None and glosa_el.text) else ""
            
            itens_ret_lista.append({
                'cod_ret': p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else "",
                'desc_ret': p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None else "PROCEDIMENTO",
                'v_inf': f"{float(v_inf_raw):.2f}",
                'v_lib': f"{float(v_lib_raw):.2f}",
                'glosa_original': glosa_original,
                'usado': False 
            })
        
        dados_guia = {'meta': meta, 'itens': itens_ret_lista, 'usado': False}

        if n_guia_prest_ret is not None and n_guia_prest_ret.text: 
            adicionar_ao_mapa(f"GUIA_{limpar_numero(n_guia_prest_ret.text)}", dados_guia)
        if n_guia_oper_ret is not None and n_guia_oper_ret.text: 
            adicionar_ao_mapa(f"OPER_{limpar_numero(n_guia_oper_ret.text)}", dados_guia)
        if carteira_ret is not None and carteira_ret.text: 
            adicionar_ao_mapa(f"CART_{limpar_numero(carteira_ret.text)}", dados_guia)
        if senha_ret is not None and senha_ret.text: 
            adicionar_ao_mapa(f"SENH_{limpar_numero(senha_ret.text)}", dados_guia)

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
        valor_final = el.text if el is not None else ""
        if aplicar_regra_especial and tag == 'situacaoProtocolo': valor_final = "6"
        ET.SubElement(protocolo, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{tag}').text = valor_final

    total_inf_geral, total_lib_geral = 0.0, 0.0

    # 3. PROCESSAMENTO - TAGS VÁLIDAS DE GUIA NO ENVIO
    tags_guias_validas = {
        'guiaconsulta', 
        'guiasadt', 
        'guiasp-sadt', 
        'guiasp_sadt',
        'guiaresumointernacao', 
        'guiahonorarios', 
        'guiahonorario',
        'guiafaturamento'
    }

    for elemento in root_env.findall('.//*', ns):
        tag_name = elemento.tag.split('}')[-1]
        
        if tag_name.lower() not in tags_guias_validas:
            continue
            
        n_guia_prest_raw = elemento.find('.//ans:numeroGuiaPrestador', ns).text if elemento.find('.//ans:numeroGuiaPrestador', ns) is not None else ""
        n_guia_oper_raw = elemento.find('.//ans:numeroGuiaOperadora', ns).text if elemento.find('.//ans:numeroGuiaOperadora', ns) is not None else ""
        carteira_raw = elemento.find('.//ans:numeroCarteira', ns).text if elemento.find('.//ans:numeroCarteira', ns) is not None else ""
        senha_el = elemento.find('.//ans:senha', ns) or elemento.find('.//ans:dadosAutorizacao/ans:senha', ns)
        senha_raw = senha_el.text if senha_el is not None and senha_el.text else ""

        n_limpo_prest = limpar_numero(n_guia_prest_raw)
        n_limpo_oper = limpar_numero(n_guia_oper_raw)

        # Identifica os itens do envio
        itens_env = elemento.findall('.//ans:procedimento', ns) if tag_name.lower() == 'guiaconsulta' else (elemento.findall('.//ans:procedimentoExecutado', ns) + elemento.findall('.//ans:despesa', ns))
        
        # Ignora blocos vazios/sem itens para evitar geração de cabeçalhos fantasmas
        if not itens_env:
            continue

        # Extração das datas para refinamento de busca por período
        if tag_name.lower() == 'guiaconsulta':
            d_ini_el = elemento.find('.//ans:dataAtendimento', ns)
            h_ini_el = elemento.find('.//ans:horaAtendimento', ns)
            d_fim_el = d_ini_el
            h_fim_el = h_ini_el
        else:
            d_ini_el = elemento.find('.//ans:dataInicioFaturamento', ns) or elemento.find('.//ans:dataExecucao', ns)
            h_ini_el = elemento.find('.//ans:horaInicioFaturamento', ns) or elemento.find('.//ans:horaInicial', ns)
            d_fim_el = elemento.find('.//ans:dataFinalFaturamento', ns) or elemento.find('.//ans:dataFimFaturamento', ns) or d_ini_el
            h_fim_el = elemento.find('.//ans:horaFinalFaturamento', ns) or elemento.find('.//ans:horaFinal', ns)

        data_ini_envio = d_ini_el.text if d_ini_el is not None else ""

        # BUSCA FLEXÍVEL CONSIDERANDO DATA/PERÍODO E ESTADO DE USO
        candidatos = (mapa_retorno.get(f"GUIA_{n_limpo_prest}", []) +
                      mapa_retorno.get(f"OPER_{n_limpo_oper}", []) +
                      mapa_retorno.get(f"OPER_{n_limpo_prest}", []) +
                      mapa_retorno.get(f"SENH_{limpar_numero(senha_raw)}", []) +
                      mapa_retorno.get(f"CART_{limpar_numero(carteira_raw)}", []))

        # Filtra opções que ainda não foram utilizadas
        opcoes_disponiveis = [c for c in candidatos if not c['usado']]

        if not opcoes_disponiveis:
            continue

        # 1º Tenta casar pelo mesmo Número + Mesma Data de Início do Faturamento
        guia_retorno = next((c for c in opcoes_disponiveis if c['meta'].get('dataInicioFat') == data_ini_envio), None)
        
        # 2º Fallback: pega o primeiro retorno disponível com aquele número se a data não bater exatamente
        if not guia_retorno:
            guia_retorno = opcoes_disponiveis[0]

        # Marca a guia do retorno como processada
        guia_retorno['usado'] = True

        m = guia_retorno['meta']
        itens_ret_disponiveis = guia_retorno['itens']
        
        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_prest_raw
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = n_guia_oper_raw if n_guia_oper_raw else m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = senha_raw if senha_raw else m.get('senha', "")
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = carteira_raw
        
        # --- DATAS E HORAS ---
        data_ini_val = data_ini_envio if data_ini_envio else m.get('dataInicioFat', "")
        envio_h_ini = h_ini_el.text if h_ini_el is not None else ""
        envio_h_fim = h_fim_el.text if h_fim_el is not None else ""
        
        if is_amazonia:
            hora_ini_val = "00:00:00"
            data_fim_val = d_fim_el.text if (d_fim_el is not None and d_fim_el.text) else data_ini_val
            hora_fim_val = "00:00:00"
        else:
            hora_ini_val = limpar_hora(envio_h_ini if envio_h_ini else m.get('horaInicioFat', "00:00:00"))
            data_fim_val = d_fim_el.text if (d_fim_el is not None and d_fim_el.text) else m.get('dataFimFat', data_ini_val)
            
            if tag_name.lower() == 'guiaconsulta':
                hora_fim_val = hora_ini_val
            else:
                hora_fim_val = limpar_hora(envio_h_fim if envio_h_fim else m.get('horaFimFat', hora_ini_val))

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataInicioFat').text = data_ini_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaInicioFat').text = hora_ini_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}dataFimFat').text = data_fim_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}horaFimFat').text = hora_fim_val
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}situacaoGuia').text = "6" if aplicar_regra_especial else m.get('situacaoGuia', "")

        t_g_inf, t_g_lib = 0.0, 0.0
        
        for idx_env, item_env in enumerate(itens_env):
            servico = item_env.find('.//ans:servicosExecutados', ns) if item_env.tag.endswith('despesa') else item_env
            v_total_el = servico.find('.//ans:valorTotal', ns) if tag_name.lower() != 'guiaconsulta' else item_env.find('.//ans:valorProcedimento', ns)
            v_env_str = f"{float(v_total_el.text):.2f}" if (v_total_el is not None and v_total_el.text) else "0.00"
            
            res = next((it for it in itens_ret_disponiveis if not it['usado'] and it['v_inf'] == v_env_str), None)
            if res: res['usado'] = True

            v_inf, v_lib = (res['v_inf'], res['v_lib']) if res else (v_env_str, "0.00")
            
            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(idx_env + 1)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = data_ini_val
            
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            proc_env = servico.find('.//ans:procedimento', ns) if servico.find('.//ans:procedimento', ns) is not None else servico
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = proc_env.find('.//ans:codigoTabela', ns).text if proc_env.find('.//ans:codigoTabela', ns) is not None else "00"
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = proc_env.find('.//ans:codigoProcedimento', ns).text if proc_env.find('.//ans:codigoProcedimento', ns) is not None else "00"
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = res['desc_ret'] if (res and res['desc_ret']) else "PROCEDIMENTO"
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf
            
            qtd_env_el = servico.find('.//ans:quantidadeExecutada', ns)
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = f"{float(qtd_env_el.text):.2f}" if (qtd_env_el is not None and qtd_env_el.text) else "1.00"
            
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_inf
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = v_lib

            v_inf_f, v_lib_f = float(v_inf), float(v_lib)
            valor_glosa_final = round(v_inf_f - v_lib_f, 2)
            if valor_glosa_final > 0:
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = f"{valor_glosa_final:.2f}"
                
                if res and res.get('glosa_original'):
                    rg_tipo = res['glosa_original']
                else:
                    rg_tipo = '1705' if is_amazonia else '1801'
                    
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = rg_tipo

            t_g_inf += v_inf_f
            t_g_lib += v_lib_f

        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{max(0, t_g_inf - t_g_lib):.2f}"
        total_inf_geral += t_g_inf
        total_lib_geral += t_g_lib

    # Totais e Epílogo
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib_geral:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{max(0, total_inf_geral - total_lib_geral):.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    return minidom.parseString(ET.tostring(novo_root, 'iso-8859-1')).toprettyxml(indent="  ", encoding='ISO-8859-1')
