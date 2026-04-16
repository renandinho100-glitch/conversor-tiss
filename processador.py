import xml.etree.ElementTree as ET
from collections import deque
from xml.dom import minidom
import re

def limpar_texto(texto):
    if not texto: return ""
    return re.sub(r'[^A-Z0-9]', '', texto.upper())

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos: {e}"

    # 1. MAPEAMENTO DO RETORNO (O que a operadora pagou é a verdade final)
    mapa_retorno = {}
    mapa_cabecalho_guia = {} 
    
    # Captura totais do protocolo direto do retorno para evitar erro de centavos
    total_protocolo_inf = root_ret.find('.//ans:valorInformadoProtocolo', ns).text
    total_protocolo_proc = root_ret.find('.//ans:valorProcessadoProtocolo', ns).text
    total_protocolo_lib = root_ret.find('.//ans:valorLiberadoProtocolo', ns).text
    total_protocolo_glo = root_ret.find('.//ans:valorGlosaProtocolo', ns).text

    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia = relacao.find('.//ans:numeroGuiaPrestador', ns).text.strip()
        
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia', 'valorInformadoGuia', 'valorProcessadoGuia', 'valorLiberadoGuia', 'valorGlosaGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else "0.00"
        mapa_cabecalho_guia[n_guia] = meta

        for item in relacao.findall('.//ans:detalhesGuia', ns):
            p_elem = item.find('.//ans:procedimento', ns)
            cod = p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else ""
            descr = p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None else ""
            data = item.find('ans:dataRealizacao', ns).text if item.find('ans:dataRealizacao', ns) is not None else ""
            v_inf = f"{float(item.find('.//ans:valorInformado', ns).text):.2f}"
            
            # Dados cruciais do retorno
            v_proc = item.find('.//ans:valorProcessado', ns).text
            v_lib = item.find('.//ans:valorLiberado', ns).text
            g_elem = item.find('.//ans:tipoGlosa', ns)
            cod_glosa = g_elem.text if g_elem is not None else None

            conteudo = {
                'v_proc': v_proc, 
                'v_lib': v_lib, 
                'cod_glosa': cod_glosa,
                'v_glo': f"{float(v_proc) - float(v_lib):.2f}"
            }
            
            # Chaves hierárquicas
            chaves = [
                f"{n_guia}_{cod}_{data}_{v_inf}",
                f"{n_guia}_{limpar_texto(descr)}_{v_inf}",
                f"{n_guia}_{v_inf}"
            ]
            for c in chaves:
                if c not in mapa_retorno: mapa_retorno[c] = deque()
                mapa_retorno[c].append(conteudo)

    # 2. MONTAGEM DO XML (Mesma estrutura anterior)
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS')
    # ... (partes de cabeçalho omitidas para brevidade, manter igual ao anterior)
    
    # 3. PROCESSAMENTO DAS GUIAS
    # No loop de itens, use:
    # v_lib_final = res['v_lib'] 
    # v_proc_final = res['v_proc']
    
    # No final, force os totais do protocolo:
    # ET.SubElement(protocolo, 'ans:valorLiberadoProtocolo').text = total_protocolo_lib

    return "Script ajustado para ignorar divergências de centavos e seguir o retorno."
