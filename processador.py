import xml.etree.ElementTree as ET
from io import BytesIO
from collections import deque
from xml.dom import minidom
import re

def limpar_texto(texto):
    """Remove caracteres especiais e espaços extras para comparar nomes."""
    if not texto: return ""
    return re.sub(r'[^A-Z0-9]', '', texto.upper())

def processar_xmls(envio_file, retorno_file):
    ns = {'ans': 'http://www.ans.gov.br/padroes/tiss/schemas'}
    ET.register_namespace('ans', "http://www.ans.gov.br/padroes/tiss/schemas")
    
    codigos_glosa_padrao = ['1099', '1199', '1999', '3099']

    try:
        tree_ret = ET.parse(retorno_file)
        root_ret = tree_ret.getroot()
        tree_env = ET.parse(envio_file)
        root_env = tree_env.getroot()
    except Exception as e:
        return f"Erro ao ler arquivos XML: {e}"

    # 1. MAPEAMENTO DO RETORNO COM HIERARQUIA REFORÇADA
    mapa_retorno = {}
    mapa_cabecalho_guia = {} 
    
    for relacao in root_ret.findall('.//ans:relacaoGuias', ns):
        n_guia_elem = relacao.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_elem is None: continue
        n_guia = n_guia_elem.text.strip()
        
        meta = {}
        for tag in ['numeroGuiaOperadora', 'senha', 'dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            elem = relacao.find(f'ans:{tag}', ns)
            meta[tag] = elem.text.strip() if (elem is not None and elem.text) else ""
        
        if not meta['dataFimFat']: meta['dataFimFat'] = meta['dataInicioFat']
        if not meta['horaFimFat']: meta['horaFimFat'] = meta['horaInicioFat']
        mapa_cabecalho_guia[n_guia] = meta

        for item in relacao.findall('.//ans:detalhesGuia', ns):
            p_elem = item.find('.//ans:procedimento', ns)
            cod = p_elem.find('ans:codigoProcedimento', ns).text if p_elem is not None else ""
            descr = p_elem.find('ans:descricaoProcedimento', ns).text if p_elem is not None else ""
            data = item.find('ans:dataRealizacao', ns).text if item.find('ans:dataRealizacao', ns) is not None else ""
            v_inf = f"{float(item.find('.//ans:valorInformado', ns).text):.2f}"
            qtd = item.find('.//ans:qtdExecutada', ns).text if item.find('.//ans:qtdExecutada', ns) is not None else "1"
            
            v_lib = float(item.find('.//ans:valorLiberado', ns).text)
            g_elem = item.find('.//ans:tipoGlosa', ns)
            cod_glosa = g_elem.text if g_elem is not None else None

            conteudo = {'v_lib': v_lib, 'cod_glosa': cod_glosa, 'cod_retorno': cod}
            
            # HIERARQUIA DE CHAVES (DA MAIS PRECISA PARA A MAIS FLEXÍVEL)
            chaves = [
                f"{n_guia}_{cod}_{data}_{v_inf}",               # 1. Exata (Guia+Cod+Data+Valor)
                f"{n_guia}_{data}_{v_inf}_{qtd}_{limpar_texto(descr)}", # 2. Descrição (Guia+Data+Valor+Nome)
                f"{n_guia}_{cod}_{v_inf}",                       # 3. Código+Valor (Ignora data alterada)
                f"{n_guia}_{limpar_texto(descr)}_{v_inf}",      # 4. Nome+Valor (Ignora cod/data alterados)
                f"{n_guia}_{v_inf}"                             # 5. Apenas Valor (Último caso na guia)
            ]
            
            for c in chaves:
                if c not in mapa_retorno: mapa_retorno[c] = deque()
                mapa_retorno[c].append(conteudo)

    # 2. ESTRUTURA DO NOVO XML
    novo_root = ET.Element('{http://www.ans.gov.br/padroes/tiss/schemas}mensagemTISS')
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

    total_inf, total_lib, processadas = 0.0, 0.0, set()

    # 3. PROCESSAMENTO
    for elemento in root_env.findall('.//*', ns):
        tag_name = elemento.tag.split('}')[-1]
        if 'guia' not in tag_name.lower() or any(x in tag_name.lower() for x in ['guiastiss', 'loteguias', 'relacaoguias']):
            continue
            
        n_guia_el = elemento.find('.//ans:numeroGuiaPrestador', ns)
        if n_guia_el is None: continue
        n_guia_env = n_guia_el.text.strip()
        
        if n_guia_env in processadas or n_guia_env not in mapa_cabecalho_guia: continue
        processadas.add(n_guia_env)

        # Regras de Senha e Carteira
        senha = ""
        if "Internacao" in tag_name:
            s_el = elemento.find('.//ans:dadosAutorizacao/ans:senha', ns)
            if s_el is not None: senha = s_el.text.strip()
        if not senha:
            s_el = elemento.find('.//ans:senha', ns)
            if s_el is not None and s_el.text: senha = s_el.text.strip()
        if not senha: senha = mapa_cabecalho_guia[n_guia_env].get('senha', "")

        cart = ""
        c_el = elemento.find('.//ans:numeroCarteira', ns)
        if c_el is not None and c_el.text: cart = c_el.text.strip()

        rel_guia = ET.SubElement(protocolo, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGuias')
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaPrestador').text = n_guia_env
        m = mapa_cabecalho_guia[n_guia_env]
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroGuiaOperadora').text = m['numeroGuiaOperadora']
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}senha').text = senha
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}numeroCarteira').text = cart
        
        for t in ['dataInicioFat', 'horaInicioFat', 'dataFimFat', 'horaFimFat', 'situacaoGuia']:
            ET.SubElement(rel_guia, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}{t}').text = m.get(t, "")

        # Coleta de Itens
        itens_envio = []
        for item_el in elemento.findall('.//ans:procedimentoExecutado', ns) + elemento.findall('.//ans:despesa', ns):
            servico = item_el.find('.//ans:servicosExecutados', ns) if item_el.tag.endswith('despesa') else item_el
            proc_dados = servico.find('.//ans:procedimento', ns) if servico.find('.//ans:procedimento', ns) is not None else servico
            
            itens_envio.append({
                'cod': proc_dados.find('.//ans:codigoProcedimento', ns).text,
                'tab': proc_dados.find('.//ans:codigoTabela', ns).text,
                'descr': proc_dados.find('.//ans:descricaoProcedimento', ns).text,
                'data': servico.find('.//ans:dataExecucao', ns).text if servico.find('.//ans:dataExecucao', ns) is not None else "",
                'v_inf': float(servico.find('.//ans:valorTotal', ns).text),
                'qtd': servico.find('.//ans:quantidadeExecutada', ns).text
            })

        t_g_inf, t_g_lib, seq = 0.0, 0.0, 1
        for item in itens_envio:
            v_str = f"{item['v_inf']:.2f}"
            
            # TENTATIVAS HIERÁRQUICAS (Inclui novas regras de flexibilidade de data/código)
            tentativas = [
                f"{n_guia_env}_{item['cod']}_{item['data']}_{v_str}", # Nível 1
                f"{n_guia_env}_{item['data']}_{v_str}_{item['qtd']}_{limpar_texto(item['descr'])}", # Nível 2
                f"{n_guia_env}_{item['cod']}_{v_str}", # Nível 3 (Data ignorada)
                f"{n_guia_env}_{limpar_texto(item['descr'])}_{v_str}", # Nível 4 (Cod e Data ignorados)
                f"{n_guia_env}_{v_str}" # Nível 5 (Apenas valor na guia)
            ]
            
            v_lib, c_glosa, res = 0.0, "1801", None
            for key in tentativas:
                if key in mapa_retorno and len(mapa_retorno[key]) > 0:
                    res = mapa_retorno[key].popleft()
                    break

            if res: v_lib, c_glosa = res['v_lib'], res['cod_glosa']
            v_glosa = round(item['v_inf'] - v_lib, 2)
            
            if v_glosa > 0.001 and (c_glosa in codigos_glosa_padrao or c_glosa is None):
                c_glosa = "1801"
            
            t_g_inf += item['v_inf']
            t_g_lib += v_lib

            det = ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}detalhesGuia')
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}sequencialItem').text = str(seq)
            seq += 1
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}dataRealizacao').text = item['data']
            ptag = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}procedimento')
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoTabela').text = item['tab']
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}codigoProcedimento').text = item['cod']
            ET.SubElement(ptag, '{http://www.ans.gov.br/padroes/tiss/schemas}descricaoProcedimento').text = item['descr']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformado').text = v_str
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}qtdExecutada').text = item['qtd']
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessado').text = v_str
            ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberado').text = f"{v_lib:.2f}"

            if v_glosa > 0.001:
                rg = ET.SubElement(det, '{http://www.ans.gov.br/padroes/tiss/schemas}relacaoGlosa')
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosa').text = f"{v_glosa:.2f}"
                ET.SubElement(rg, '{http://www.ans.gov.br/padroes/tiss/schemas}tipoGlosa').text = str(c_glosa)

        # Totais
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorInformadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorProcessadoGuia').text = f"{t_g_inf:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorLiberadoGuia').text = f"{t_g_lib:.2f}"
        ET.SubElement(rel_guia, '{http://www.ans.gov.br/padroes/tiss/schemas}valorGlosaGuia').text = f"{t_g_inf - t_g_lib:.2f}"
        total_inf += t_g_inf
        total_lib += t_g_lib

    # 4. TOTAIS FINAIS
    for b, s in [(protocolo, "Protocolo"), (demonstrativo, "Geral")]:
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorInformado{s}').text = f"{total_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorProcessado{s}').text = f"{total_inf:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorLiberado{s}').text = f"{total_lib:.2f}"
        ET.SubElement(b, f'{{http://www.ans.gov.br/padroes/tiss/schemas}}valorGlosa{s}').text = f"{total_inf - total_lib:.2f}"

    epilogo = ET.SubElement(novo_root, '{http://www.ans.gov.br/padroes/tiss/schemas}epilogo')
    ET.SubElement(epilogo, '{http://www.ans.gov.br/padroes/tiss/schemas}hash').text = "0" * 32
    return minidom.parseString(ET.tostring(novo_root, 'iso-8859-1')).toprettyxml(indent="  ", encoding='ISO-8859-1')
