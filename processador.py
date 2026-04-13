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

    # 2. BUSCA DO LOTE NO ENVIO (IGNORANDO NAMESPACES)
    # O '*' faz o script procurar a tag numeroLote em qualquer lugar, ignorando o 'ans:'
    lote_envio_elem = root_env.find('.//{*}numeroLote')
    
    if lote_envio_elem is None:
        # Segunda tentativa: procurar por numeroLotePrestador (comum em outros tipos de guia)
        lote_envio_elem = root_env.find('.//{*}numeroLotePrestador')

    if lote_envio_elem is None:
        raise Exception("Erro: Nao encontrei a tag <numeroLote> no arquivo de ENVIO. Verifique se o arquivo e um XML TISS valido.")
    
    lote_procurado = lote_envio_elem.text.strip()
    print(f"Lote encontrado no envio: {lote_procurado}")

    # 3. LOCALIZAR O LOTE NO RETORNO (ARQUIVO GIGANTE)
    demonstrativo_correto = None
    for demo in root_ret.findall('.//{*}demonstrativoAnaliseConta'):
        lote_no_retorno = demo.find('.//{*}numeroLotePrestador')
        
        if lote_no_retorno is not None and lote_no_retorno.text.strip() == lote_procurado:
            demonstrativo_correto = demo
            break
    
    if demonstrativo_correto is None:
        raise Exception(f"Erro: O Lote {lote_procurado} nao foi encontrado dentro do arquivo de RETORNO gigante.")

    # 4. MAPEAMENTO DO RETORNO
    mapa_itens_retorno = {}
    for relacao in demonstrativo_correto.findall('.//{*}relacaoGuias'):
        guia_elem = relacao.find('{*}numeroGuiaPrestador')
        if guia_elem is None: continue
        n_guia = guia_elem.text
        
        meta_guia = {}
        tags_meta = ['numeroGuiaOperadora', 'senha', 'numeroCarteira', 'dataInicioFat', 
                     'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']
        for tag in tags_meta:
            elem = relacao.find(f'{{*}}{tag}')
            meta_guia[tag] = elem.text if elem is not None else ""

        for item in relacao.findall('.//{*}detalhesGuia'):
            cod = item.find('.//{*}codigoProcedimento').text
            data = item.find('{*}dataRealizacao').text
            v_inf = f"{float(item.find('.//{*}valorInformado').text):.2f}"
            v_lib = float(item.find('.//{*}valorLiberado').text)
            
            tag_glosa = item.find('.//{*}tipoGlosa')
            cod_glosa = tag_glosa.text if tag_glosa is not None else None
            
            chave_mestra = f"{n_guia}_{cod}_{data}_{v_inf}"
            if chave_mestra not in mapa_itens_retorno:
                mapa_itens_retorno[chave_mestra] = deque()
            mapa_itens_retorno[chave_mestra].append({'v_lib': v_lib, 'cod_glosa': cod_glosa, 'meta': meta_guia})

    # 5. GERAR NOVO XML (USANDO NAMESPACE PADRÃO ANS)
    ans_url = "http://www.ans.gov.br/padroes/tiss/schemas"
    ET.register_namespace('ans', ans_url)
    novo_root = ET.Element(f'{{{ans_url}}}mensagemTISS')
    
    cabecalho_orig = root_ret.find('.//{*}cabecalho')
    if cabecalho_orig is not None: novo_root.append(cabecalho_orig)
    
    op_para_prest = ET.SubElement(novo_root, f'{{{ans_url}}}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, f'{{{ans_url}}}demonstrativosRetorno')
    novo_demo = ET.SubElement(demons_ret, f'{{{ans_url}}}demonstrativoAnaliseConta')
    
    for tag_f in ['cabecalhoDemonstrativo', 'dadosPrestador']:
        elem = demonstrativo_correto.find(f'{{*}}{tag_f}')
        if elem is not None: novo_demo.append(elem)
        
    dados_conta = ET.SubElement(novo_demo, f'{{{ans_url}}}dadosConta')
    protocolo = ET.SubElement(dados_conta, f'{{{ans_url}}}dadosProtocolo')
    
    tags_p = ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']
    for t in tags_p:
        elem = demonstrativo_correto.find(f'.//{{*}}{t}')
        ET.SubElement(protocolo, f'{{{ans_url}}}{t}').text = elem.text if elem is not None else ""

    # 6. PROCESSAR GUIAS DO ENVIO
    total_geral_inf, total_geral_lib = 0.0, 0.0
    for guia_envio in root_env.findall('.//{*}guiaResumoInternacao'):
        n_guia_env = guia_envio.find('.//{*}numeroGuiaPrestador').text
        relacao_guias = ET.SubElement(protocolo, f'{{{ans_url}}}relacaoGuias')
        ET.SubElement(relacao_guias, f'{{{ans_url}}}numeroGuiaPrestador').text = n_guia_env
        
        meta_encontrada = False
        itens_guia = []
        # Procedimentos
        for p in guia_envio.findall('.//{*}procedimentoExecutado'):
            d = p.find('{*}procedimento')
            itens_guia.append({
                'cod': d.find('{*}codigoProcedimento').text, 
                'tab': d.find('{*}codigoTabela').text, 
                'descr': d.find('{*}descricaoProcedimento').text, 
                'data': p.find('{*}dataExecucao').text, 
                'v_inf': float(p.find('{*}valorTotal').text), 
                'qtd': p.find('{*}quantidadeExecutada').text
            })
        # Despesas
        for d in guia_envio.findall('.//{*}despesa'):
            s = d.find('{*}servicosExecutados')
            itens_guia.append({
                'cod': s.find('{*}codigoProcedimento').text, 
                'tab': s.find('{*}codigoTabela').text, 
                'descr': s.find('{*}descricaoProcedimento').text, 
                'data': s.find('{*}dataExecucao').text, 
                'v_inf': float(s.find('{*}valorTotal').text), 
                'qtd': s.find('{*}quantidadeExecutada').text
            })

        total_guia_inf, total_guia_lib = 0.0, 0.0
        seq = 1
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
