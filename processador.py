import xml.etree.ElementTree as ET
from io import BytesIO
from collections import deque
from xml.dom import minidom

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    codigos_para_substituir = ['1099', '1199', '1999', '3099']

    # 1. LER ARQUIVOS
    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}"

    # 2. MAPEAMENTO DO RETORNO
    mapa_itens_retorno = {}
    mapa_cabecalho_guia = {} 
    
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia_elem = relacao.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_elem is None: continue
        n_guia = n_guia_elem.text.strip()
        
        meta = {}
        tags_meta = ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 
                     'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']
        for tag in tags_meta:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text if elem is not None else ""
        mapa_cabecalho_guia[n_guia] = meta

        for item in relacao.findall('.//ans:detalhesGuia', ns):
            cod_elem = item.find('.//ans:codigoProcedimento', ns)
            if cod_elem is None: continue
            
            cod = cod_elem.text
            data = item.find('.//ans:dataRealizacao', ns).text
            v_inf_val = float(item.find('.//ans:valorInformado', ns).text)
            v_inf_str = f"{v_inf_val:.2f}"
            v_lib = float(item.find('.//ans:valorLiberado', ns).text)
            
            tag_glosa = item.find('.//ans:tipoGlosa', ns)
            cod_glosa = tag_glosa.text if tag_glosa is not None else None
            
            # Chaves para busca
            chave_exata = f"{n_guia}_{cod}_{data}_{v_inf_str}"
            chave_flex = f"{n_guia}_{cod}_FLEX_{v_inf_str}"
            
            conteudo = {'v_lib': v_lib, 'cod_glosa': cod_glosa}
            for c in [chave_exata, chave_flex]:
                if c not in mapa_itens_retorno:
                    mapa_itens_retorno[c] = deque()
                mapa_itens_retorno[c].append(conteudo)

    # 3. ESTRUTURA DO NOVO XML
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS')
    if (cab := root_ret.find('ans:cabecalho', ns)) is not None: novo_root.append(cab)

    op_para_prest = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}operadoraParaPrestador')
    demons_ret = ET.SubElement(op_para_prest, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativosRetorno')
    demonstrativo = ET.SubElement(demons_ret, '{http://www.ans.gov.br/padroes/tiss/schemas}demonstrativoAnaliseConta')
    
    if (cab_demons := root_ret.find('.//ans:cabecalhoDemonstrativo', ns)) is not None: demonstrativo.append(cab_demons)
    if (dados_prest := root_ret.find('.//ans:dadosPrestador', ns)) is not None: demonstrativo.append(dados_prest)

    dados_conta = ET.SubElement(demonstrativo, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosConta')
    protocolo = ET.SubElement(dados_conta, '{http://www.ans.gov.br/padroes/tiss/schemas}dadosProtocolo')
    
    for tag in ['numeroLotePrestador', 'numeroProtocolo', 'dataProtocolo', 'situacaoProtocolo']:
        elem = root_ret.find(f'.//ans:{tag}', ns)
        ET.SubElement(protocolo, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{tag}').text = elem.text if elem is not None else ""

    total_geral_inf = 0.0
    total_geral_lib = 0.0

    # 4. BUSCA FLEXÍVEL DE GUIAS NO ENVIO (Resolve o problema do guiaSP-SADT)
    # Procuramos qualquer elemento que tenha 'guia' no nome da tag
    for guia in root_env.findall('.//*', ns):
        if 'guia' not in guia.tag.lower() or 'guiastiss' in guia.tag.lower() or 'loteguias' in guia.tag.lower():
            continue
            
        n_guia_elem = guia.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_elem is None: continue
        n_guia_env = n_guia_elem.text.strip()
        
        # Só processa se a guia existir no retorno
        if n_guia_env not in mapa_cabecalho_guia: continue

        # Beneficiário
        carteira_envio = ""
        if (eb := guia.find('.//ans:dadosBeneficiario', ns)) is not None:
            if (ec := eb.find('ans:numeroCarteira', ns)) is not None: carteira_envio = ec.text

        relacao_guias = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        
        m = mapa_cabecalho_guia[n_guia_env]
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = m['numeroGuiaOperadora']
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = m['senha']
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = carteira_envio
        for t in ['dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            ET.SubElement(relacao_guias, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{t}').text = m[t]

        # Itens
        itens_para_processar = []
        for p in guia.findall('.//ans:procedimentoExecutado', ns):
            d = p.find('ans:procedimento', ns)
            itens_para_processar.append({
                'cod': d.find('ans:codigoProcedimento', ns).text, 'tab': d.find('ans:codigoTabela', ns).text, 
                'descr': d.find('ans:descricaoProcedimento', ns).text, 'data': p.find('ans:dataExecucao', ns).text,
                'v_inf': float(p.find('ans:valorTotal', ns).text), 'qtd': p.find('ans:quantidadeExecutada', ns).text
            })
        for d in guia.findall('.//ans:despesa', ns):
            s = d.find('ans:servicosExecutados', ns)
            itens_para_processar.append({
                'cod': s.find('ans:codigoProcedimento', ns).text, 'tab': s.find('ans:codigoTabela', ns).text, 
                'descr': s.find('ans:descricaoProcedimento', ns).text, 'data': s.find('ans:dataExecucao', ns).text,
                'v_inf': float(s.find('ans:valorTotal', ns).text), 'qtd': s.find('ans:quantidadeExecutada', ns).text
            })

        t_guia_inf, t_guia_lib, seq = 0.0, 0.0, 1
        for item in itens_para_processar:
            v_inf_str = f"{item['v_inf']:.2f}"
            ch_exata = f"{n_guia_env}_{item['cod']}_{item['data']}_{v_inf_str}"
            ch_flex = f"{n_guia_env}_{item['cod']}_FLEX_{v_inf_str}"
            
            v_lib, cod_glosa, res = 0.0, "1801", None
            if ch_exata in mapa_itens_retorno and len(mapa_itens_retorno[ch_exata]) > 0:
                res = mapa_itens_retorno[ch_exata].popleft()
            elif ch_flex in mapa_itens_retorno and len(mapa_itens_retorno[ch_flex]) > 0:
                res = mapa_itens_retorno[ch_flex].popleft()

            if res:
                v_lib, cod_glosa = res['v_lib'], res['cod_glosa']

            if v_lib > item['v_inf']: v_lib = item['v_inf']
            v_glosa = round(item['v_inf'] - v_lib, 2)
            
            # Se houver glosa real e for código genérico, vira 1801
            if v_glosa > 0.001 and (cod_glosa in codigos_para_substituir or cod_glosa is None):
                cod_glosa = "1801"
            
            t_guia_inf += item['v_inf']
            t_guia_lib += v_lib

            det = ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(seq)
            seq += 1
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = item['data']
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = item['tab']
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = item['cod']
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = item['descr']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_inf_str
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = item['qtd']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_inf_str
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = f"{v_lib:.2f}"

            if v_glosa > 0.001:
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = f"{v_glosa:.2f}"
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = str(cod_glosa)

        # Totais da Guia
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_guia_inf:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_guia_inf:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_guia_lib:.2f}"
        ET.SubElement(relacao_guias, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{t_guia_inf - t_guia_lib:.2f}"
        total_geral_inf += t_guia_inf
        total_geral_lib += t_guia_lib

    # 5. TOTAIS FINAIS
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_geral_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_geral_lib:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{total_geral_inf - total_geral_lib:.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    
    rough = ET.tostring(novo_root, 'iso-8859-1')
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding='ISO-8859-1')
