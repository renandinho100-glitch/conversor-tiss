import xml.etree.ElementTree as ET
from io import BytesIO
from collections import deque
from xml.dom import minidom

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    codigos_para_substituir = ['1099', '1199', '1999', '3099']

    # 1. LER ARQUIVOS
    tree_env = ET.parse(envio_file)
    root_env = tree_env.getroot()
    
    tree_ret = ET.parse(retorno_file)
    root_ret = tree_ret.getroot()

    # 2. IDENTIFICAR O NÚMERO DO LOTE NO ENVIO
    # Procuramos o lote dentro da guia de resumo ou outras tags comuns de lote
    lote_envio_elem = root_env.find('.//ans:numeroLotePrestador', ns)
    if lote_envio_elem is None:
        # Se não achar na tag específica, tenta pegar de campos de identificação da guia
        lote_envio_elem = root_env.find('.//ans:identificacaoGuia/ans:numeroGuiaPrestador', ns) # Backup
    
    if lote_envio_elem is None:
        raise Exception("Não foi possível encontrar o Número do Lote no arquivo de ENVIO.")
    
    lote_procurado = lote_envio_elem.text
    print(f"Buscando no retorno o Lote: {lote_procurado}")

    # 3. LOCALIZAR O LOTE CORRETO NO RETORNO GIGANTE
    demonstrativo_correto = None
    for demo in root_ret.findall('.//ans:demonstrativoAnaliseConta', ns):
        lote_no_retorno = demo.find('.//ans:numeroLotePrestador', ns)
        if lote_no_retorno is not None and lote_no_retorno.text == lote_procurado:
            demonstrativo_correto = demo
            break
    
    if demonstrativo_correto is None:
        raise Exception(f"Lote {lote_procurado} não encontrado dentro do arquivo de retorno fornecido.")

    # 4. MAPEAMENTO DO RETORNO (Apenas do Lote Localizado)
    mapa_itens_retorno = {}
    
    for relacao in demonstrativo_correto.findall('.//ans:relacaoGuias', ns):
        n_guia = relacao.find('ans:numeroGuiaPrestador', ns).text
        
        meta_guia = {}
        tags_meta = ['numeroGuiaOperadora', 'senha', 'numeroCarteira', 'dataInicioFat', 
                     'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']
        for tag in tags_meta:
            elem = relacao.find(f'ans:{tag}', ns)
            meta_guia[tag] = elem.text if elem is not None else ""

        for item in relacao.findall('ans:detalhesGuia', ns):
            cod = item.find('.//ans:codigoProcedimento', ns).text
            data = item.find('ans:dataRealizacao', ns).text
            v_inf = f"{float(item.find('.//ans:valorInformado', ns).text):.2f}"
            v_lib = float(item.find('.//ans:valorLiberado', ns).text)
            
            tag_glosa = item.find('.//ans:tipoGlosa', ns)
            cod_glosa = tag_glosa.text if tag_glosa is not None else None
            
            chave_mestra = f"{n_guia}_{cod}_{data}_{v_inf}"
            
            if chave_mestra not in mapa_itens_retorno:
                mapa_itens_retorno[chave_mestra] = deque()
            
            mapa_itens_retorno[chave_mestra].append({
                'v_lib': v_lib, 
                'cod_glosa': cod_glosa,
                'meta': meta_guia
            })

    # 5. CONSTRUIR ESTRUTURA DO NOVO XML
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS')
    
    cabecalho_orig = root_ret.find('ans:cabecalho', ns)
    if cabecalho_orig is not None: novo_root.append(cabecalho_orig)

    op_para_prest = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativosRetorno')
    novo_demonstrativo = ET.SubElement(demons_ret, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativoAnaliseConta')
    
    # Copia as tags fixas do demonstrativo localizado
    for tag_fixa in ['cabecalhoDemonstrativo', 'dadosPrestador']:
        elem = demonstrativo_correto.find(f'ans:{tag_fixa}', ns)
        if elem is not None: novo_demonstrativo.append(elem)

    dados_conta = ET.SubElement(novo_demonstrativo, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosConta')
    protocolo = ET.SubElement(dados_conta, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosProtocolo')
    
    # Copia dados do protocolo do lote localizado
    tags_prot = ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']
    for tag in tags_prot:
        elem = demonstrativo_correto.find(f'.//ans:{tag}', ns)
        ET.SubElement(protocolo, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{tag}').text = elem.text if elem is not None else ""

    total_geral_inf = 0.0
    total_geral_lib = 0.0

    # 6. PROCESSAR ENVIO (Igual v14, mas usando o mapa do lote filtrado)
    for guia_envio in root_env.findall('.//ans:guiaResumoInternacao', ns):
        n_guia_env = guia_envio.find('.//ans:numeroGuiaPrestador', ns).text
        relacao_guias = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        
        meta_encontrada = False
        itens_para_processar = []
        
        # Coleta de Itens
        for p in guia_envio.findall('.//ans:procedimentoExecutado', ns):
            d = p.find('ans:procedimento', ns)
            itens_para_processar.append({'cod': d.find('ans:codigoProcedimento', ns).text, 'tab': d.find('ans:codigoTabela', ns).text, 'descr': d.find('ans:descricaoProcedimento', ns).text, 'data': p.find('ans:dataExecucao', ns).text, 'v_inf': float(p.find('ans:valorTotal', ns).text), 'qtd': p.find('ans:quantidadeExecutada', ns).text})
        for d in guia_envio.findall('.//ans:despesa', ns):
            s = d.find('ans:servicosExecutados', ns)
            itens_para_processar.append({'cod': s.find('ans:codigoProcedimento', ns).text, 'tab': s.find('ans:codigoTabela', ns).text, 'descr': s.find('ans:descricaoProcedimento', ns).text, 'data': s.find('ans:dataExecucao', ns).text, 'v_inf': float(s.find('ans:valorTotal', ns).text), 'qtd': s.find('ans:quantidadeExecutada', ns).text})

        total_guia_inf = 0.0
        total_guia_lib = 0.0
        seq = 1

        for item in itens_para_processar:
            chave_busca = f"{n_guia_env}_{item['cod']}_{item['data']}_{item['v_inf']:.2f}"
            v_lib = 0.0
            cod_glosa = "1801"

            if chave_busca in mapa_itens_retorno and len(mapa_itens_retorno[chave_busca]) > 0:
                dados_res = mapa_itens_retorno[chave_busca].popleft()
                v_lib = dados_res['v_lib']
                cod_glosa = dados_res['cod_glosa']
                
                if not meta_encontrada:
                    for m_tag in tags_meta:
                        ET.SubElement(relacao_guias, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{m_tag}').text = dados_res['meta'].get(m_tag, "")
                    meta_encontrada = True

            if v_lib > item['v_inf']: v_lib = item['v_inf']
            valor_glosa = round(item['v_inf'] - v_lib, 2)
            if valor_glosa > 0.001 and (cod_glosa in codigos_para_substituir or cod_glosa is None):
                cod_glosa = "1801"
            
            total_guia_inf += item['v_inf']
            total_guia_lib += v_lib

            det = ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(seq)
            seq += 1
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = item['data']
            p_tag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = item['tab']
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = item['cod']
            ET.SubElement(p_tag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = item['descr']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = f"{item['v_inf']:.2f}"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = item['qtd']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = f"{item['v_inf']:.2f}"
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = f"{v_lib:.2f}"

            if valor_glosa > 0.001:
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = f"{valor_glosa:.2f}"
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = str(cod_glosa)

        # Totais Guia
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{total_guia_inf:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{total_guia_inf:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{total_guia_lib:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{total_guia_inf - total_guia_lib:.2f}"
        total_geral_inf += total_guia_inf
        total_geral_lib += total_guia_lib

    # 7. TOTAIS GERAIS
    for b, s in [(protocolo, "Protocolo"), (novo_demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_geral_lib:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{total_geral_inf - total_geral_lib:.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32

    rough_string = ET.tostring(novo_root, 'iso-8859-1')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding='ISO-8859-1')
