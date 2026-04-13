import xml.etree.ElementTree as ET
from io import BytesIO
from collections import deque
from xml.dom import minidom

def processar_xmls(envio_file, retorno_file):
    # 1. LER ARQUIVOS
    tree_env = ET.parse(envio_file)
    root_env = tree_env.getroot()
    
    tree_ret = ET.parse(retorno_file)
    root_ret = tree_ret.getroot()

    # 2. BUSCA DO LOTE NO ENVIO (USANDO LÓGICA INFALÍVEL PARA TISS 4.01)
    lote_envio_elem = None
    # Esta linha procura qualquer tag que termine com 'numeroLote', ignorando o prefixo ans:
    for elem in root_env.iter():
        if elem.tag.split('}')[-1] == 'numeroLote':
            lote_envio_elem = elem
            break
    
    # Se não achar numeroLote, tenta numeroLotePrestador (algumas operadoras mudam)
    if lote_envio_elem is None:
        for elem in root_env.iter():
            if elem.tag.split('}')[-1] == 'numeroLotePrestador':
                lote_envio_elem = elem
                break

    if lote_envio_elem is None:
        raise Exception("Nao foi possivel encontrar o Numero do Lote no arquivo de ENVIO. Verifique se o arquivo esta correto.")
    
    lote_procurado = lote_envio_elem.text.strip()
    print(f"Lote identificado: {lote_procurado}")

    # 3. LOCALIZAR O LOTE NO RETORNO (ARQUIVO GIGANTE)
    demonstrativo_correto = None
    # Procuramos o bloco de demonstrativo
    for demo in root_ret.iter():
        if demo.tag.split('}')[-1] == 'demonstrativoAnaliseConta':
            # Dentro desse demonstrativo, procuramos o lote que bate com o envio
            for filho in demo.iter():
                if filho.tag.split('}')[-1] == 'numeroLotePrestador':
                    if filho.text and filho.text.strip() == lote_procurado:
                        demonstrativo_correto = demo
                        break
            if demonstrativo_correto: break
    
    if demonstrativo_correto is None:
        raise Exception(f"O Lote {lote_procurado} nao foi encontrado dentro do arquivo de RETORNO gigante enviado.")

    # 4. MAPEAMENTO DO RETORNO (Deste Lote Específico)
    mapa_itens_retorno = {}
    # Procuramos as guias dentro do demonstrativo achado
    for relacao in demonstrativo_correto.iter():
        if relacao.tag.split('}')[-1] == 'relacaoGuias':
            n_guia_elem = None
            for f in relacao:
                if f.tag.split('}')[-1] == 'numeroGuiaPrestador':
                    n_guia_elem = f
                    break
            
            if n_guia_elem is None: continue
            n_guia = n_guia_elem.text
            
            meta_guia = {}
            tags_meta = ['numeroGuiaOperadora', 'senha', 'numeroCarteira', 'dataInicioFat', 
                         'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']
            
            for f in relacao:
                tag_limpa = f.tag.split('}')[-1]
                if tag_limpa in tags_meta:
                    meta_guia[tag_limpa] = f.text if f.text else ""

            # Detalhes dos Itens
            for item in relacao.iter():
                if item.tag.split('}')[-1] == 'detalhesGuia':
                    cod, data, v_inf, v_lib, cod_glosa = "", "", "0.00", 0.0, None
                    for info in item.iter():
                        t = info.tag.split('}')[-1]
                        if t == 'codigoProcedimento': cod = info.text
                        if t == 'dataRealizacao': data = info.text
                        if t == 'valorInformado': v_inf = f"{float(info.text):.2f}"
                        if t == 'valorLiberado': v_lib = float(info.text)
                        if t == 'tipoGlosa': cod_glosa = info.text
                    
                    chave = f"{n_guia}_{cod}_{data}_{v_inf}"
                    if chave not in mapa_itens_retorno: mapa_itens_retorno[chave] = deque()
                    mapa_itens_retorno[chave].append({'v_lib': v_lib, 'cod_glosa': cod_glosa, 'meta': meta_guia})

    # 5. GERAR NOVO XML
    ans_url = "http://www.ans.gov.br/padroes/tiss/schemas"
    ET.register_namespace('ans', ans_url)
    novo_root = ET.Element(f'{{{ans_url}}}mensagemTISS')
    
    # Cabeçalho
    for f in root_ret:
        if f.tag.split('}')[-1] == 'cabecalho':
            novo_root.append(f)
            break
    
    op_para_prest = ET.SubElement(novo_root, f'{{{ans_url}}}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, f'{{{ans_url}}}demonstrativosRetorno')
    novo_demo = ET.SubElement(demons_ret, f'{{{ans_url}}}demonstrativoAnaliseConta')
    
    for tag_f in ['cabecalhoDemonstrativo', 'dadosPrestador']:
        for f in demonstrativo_correto:
            if f.tag.split('}')[-1] == tag_f:
                novo_demo.append(f)
                break
        
    dados_conta = ET.SubElement(novo_demo, f'{{{ans_url}}}dadosConta')
    protocolo = ET.SubElement(dados_conta, f'{{{ans_url}}}dadosProtocolo')
    
    tags_p = ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']
    for t in tags_p:
        valor = ""
        for f in demonstrativo_correto.iter():
            if f.tag.split('}')[-1] == t:
                valor = f.text
                break
        ET.SubElement(protocolo, f'{{{ans_url}}}{t}').text = valor if valor else ""

    # 6. PROCESSAR GUIAS DO ENVIO
    total_geral_inf, total_geral_lib = 0.0, 0.0
    for guia_envio in root_env.iter():
        if guia_envio.tag.split('}')[-1] == 'guiaResumoInternacao':
            n_guia_env = ""
            for f in guia_envio.iter():
                if f.tag.split('}')[-1] == 'numeroGuiaPrestador':
                    n_guia_env = f.text
                    break
            
            relacao_guias = ET.SubElement(protocolo, f'{{{ans_url}}}relacaoGuias')
            ET.SubElement(relacao_guias, f'{{{ans_url}}}numeroGuiaPrestador').text = n_guia_env
            
            meta_encontrada = False
            itens_guia = []
            
            # Coleta Procedimentos e Despesas
            for proc in guia_envio.iter():
                t_proc = proc.tag.split('}')[-1]
                if t_proc in ['procedimentoExecutado', 'despesa']:
                    item_dic = {}
                    for f in proc.iter():
                        tl = f.tag.split('}')[-1]
                        if tl == 'codigoProcedimento': item_dic['cod'] = f.text
                        if tl == 'codigoTabela': item_dic['tab'] = f.text
                        if tl == 'descricaoProcedimento': item_dic['descr'] = f.text
                        if tl == 'dataExecucao': item_dic['data'] = f.text
                        if tl == 'valorTotal': item_dic['v_inf'] = float(f.text)
                        if tl == 'quantidadeExecutada': item_dic['qtd'] = f.text
                    if 'cod' in item_dic: itens_guia.append(item_dic)

            total_guia_inf, total_guia_lib, seq = 0.0, 0.0, 1
            for item in itens_guia:
                chave = f"{n_guia_env}_{item['cod']}_{item['data']}_{item['v_inf']:.2f}"
                v_lib, cod_glosa = 0.0, "1801"
                if chave in mapa_itens_retorno and len(mapa_itens_retorno[chave]) > 0:
                    res = mapa_itens_retorno[chave].popleft()
                    v_lib, cod_glosa = res['v_lib'], res['cod_glosa']
                    if not meta_encontrada:
                        for mt in tags_meta: ET.SubElement(relacao_guias, f'{{{ans_url}}}{mt}').text = res['meta'].get(mt, "")
                        meta_encontrada = True
                
                if v_lib > item['v_inf']: v_lib = item['v_inf']
                v_glosa = round(item['v_inf'] - v_lib, 2)
                if v_glosa > 0.001 and (cod_glosa in ['1099', '1199', '1999', '3099'] or cod_glosa is None): cod_glosa = "1801"
                
                total_guia_inf += item['v_inf']
                total_guia_lib += v_lib
                
                det = ET.SubElement(relacao_guias, f'{{{ans_url}}}detalhesGuia')
                ET.SubElement(det, f'{{{ans_url}}}sequencialItem').text = str(seq)
                seq += 1
                ET.SubElement(det, f'{{{ans_url}}}dataRealizacao').text = item['data']
                prc = ET.SubElement(det, f'{{{ans_url}}}procedimento')
                ET.SubElement(prc, f'{{{ans_url}}}codigoTabela').text = item['tab']
                ET.SubElement(prc, f'{{{ans_url}}}codigoProcedimento').text = item['cod']
                ET.SubElement(prc, f'{{{ans_url}}}descricaoProcedimento').text = item['descr']
                ET.SubElement(det, f'{{{ans_url}}}valorInformado').text = f"{item['v_inf']:.2f}"
                ET.SubElement(det, f'{{{ans_url}}}qtdExecutada').text = item['qtd']
                ET.SubElement(det, f'{{{ans_url}}}valorProcessado').text = f"{item['v_inf']:.2f}"
                ET.SubElement(det, f'{{{ans_url}}}valorLiberado').text = f"{v_lib:.2f}"
                if v_glosa > 0.001:
                    gl = ET.SubElement(det, f'{{{ans_url}}}relacaoGlosa')
                    ET.SubElement(gl, f'{{{ans_url}}}valorGlosa').text = f"{v_glosa:.2f}"
                    ET.SubElement(gl, f'{{{ans_url}}}tipoGlosa').text = str(cod_glosa)

            ET.SubElement(relacao_guias, f'{{{ans_url}}}valorInformadoGuia').text = f"{total_guia_inf:.2f}"
            ET.SubElement(relacao_guias, f'{{{ans_url}}}valorProcessadoGuia').text = f"{total_guia_inf:.2f}"
            ET.SubElement(relacao_guias, f'{{{ans_url}}}valorLiberadoGuia').text = f"{total_guia_lib:.2f}"
            ET.SubElement(relacao_guias, f'{{{ans_url}}}valorGlosaGuia').text = f"{total_guia_inf - total_guia_lib:.2f}"
            total_geral_inf += total_guia_inf
            total_geral_lib += total_guia_lib

    # 7. TOTAIS GERAIS
    for b, s in [(protocolo, "Protocolo"), (novo_demo, "Geral")]:
        ET.SubElement(b, f'{{{ans_url}}}valorInformado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{{ans_url}}}valorProcessado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{{ans_url}}}valorLiberado{s}').text = f"{total_geral_lib:.2f}"
        ET.SubElement(b, f'{{{ans_url}}}valorGlosa{s}').text = f"{total_geral_inf - total_geral_lib:.2f}"

    epilogo = ET.SubElement(novo_root, f'{{{ans_url}}}epilogo')
    ET.SubElement(epilogo, f'{{{ans_url}}}hash').text = "0" * 32
    
    rough = ET.tostring(novo_root, 'ISO-8859-1')
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding='ISO-8859-1')
