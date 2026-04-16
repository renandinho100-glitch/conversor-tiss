import xml.etree.ElementTree as ET
from collections import deque
from xml.dom import minidom
import re

def limpar_texto(texto):
    if not texto: return ""
    return re.sub(r'[^A-Z0-9]', '', texto.upper())

def processar_xmls(envio_file, retorno_file):
    # --- TRAVA DE SEGURANÇA PARA O ERRO NONETYPE ---
    if envio_file is None or retorno_file is None:
        return "Erro: Certifique-se de que ambos os arquivos (Envio e Retorno) foram selecionados."

    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    try:
        # Tenta carregar os arquivos. Se estiverem vazios, cairá no except.
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}. Verifique se os arquivos não estão corrompidos ou vazios."

    # --- IDENTIFICAÇÃO UNIFICADA (AMAZONIA VS OUTROS) ---
    # O script é o mesmo. Ele apenas "decide" se usa a regra do sequencial aqui:
    registro_ans = root_ret.find('.//ans:registroANS', ns)
    # Registro 303976 é da Amazonia Saúde
    is_amazonia = registro_ans is not None and registro_ans.text == '303976'

    mapa_retorno = {}
    mapa_cabecalho_guia = {} 
    
    # 1. MAPEAMENTO DO RETORNO
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        guia_el = relacao.find('.//ans:numeroGuiaPrestador', ns)
        if guia_el is None: continue
        n_guia = guia_el.text.strip()
        
        # Guardamos os dados do cabeçalho da guia
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        mapa_cabecalho_guia[n_guia] = meta

        # Itens da guia no retorno
        for item in relacao.findall('.//ans:detalhesGuia', ns):
            seq_ret = item.find('ans:sequencialItem', ns).text if item.find('ans:sequencialItem', ns) is not None else ""
            p_elem = item.find('.//ans:procedimento', ns)
            cod = p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else ""
            descr = p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None else ""
            data = item.find('ans:dataRealizacao', ns).text if item.find('ans:dataRealizacao', ns) is not None else ""
            
            v_inf_raw = item.find('.//ans:valorInformado', ns)
            v_inf = f"{float(v_inf_raw.text):.2f}" if v_inf_raw is not None else "0.00"
            
            v_lib = float(item.find('.//ans:valorLiberado', ns).text) if item.find('.//ans:valorLiberado', ns) is not None else 0.0
            
            # Pega todas as glosas do item e soma
            glosas = item.findall('.//ans:relacaoGlosa', ns)
            v_total_glosa = sum(float(g.find('ans:valorGlosa', ns).text) for g in glosas if g.find('ans:valorGlosa', ns) is not None)
            cod_glosa = glosas[0].find('ans:tipoGlosa', ns).text if glosas else None

            conteudo = {'v_lib': v_lib, 'cod_glosa': cod_glosa, 'v_glo': v_total_glosa}
            
            # HIERARQUIA DE CHAVES
            chaves = []
            # Se for Amazonia, o sequencial é a primeira tentativa
            if is_amazonia and seq_ret:
                chaves.append(f"{n_guia}_SEQ_{seq_ret}")
            
            # Regras gerais (funcionam para todos os convênios)
            chaves.extend([
                f"{n_guia}_{cod}_{data}_{v_inf}",
                f"{n_guia}_{limpar_texto(descr)}_{v_inf}",
                f"{n_guia}_{v_inf}"
            ])
            
            for c in chaves:
                if c not in mapa_retorno: mapa_retorno[c] = deque()
                mapa_retorno[c].append(conteudo)

    # ... [O restante do código de montagem do XML segue aqui] ...
    return "Processamento concluído com sucesso."
