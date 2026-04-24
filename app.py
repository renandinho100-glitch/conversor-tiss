import streamlit as st
from processador import extrair_metadados, processar_xmls # Nomes sincronizados aqui

st.set_page_config(page_title="Processador TISS", layout="wide", page_icon="📑")

# Estilização básica
st.title("📑 Processador de Retorno TISS")
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload dos Arquivos")
    file_envio = st.file_uploader("Arquivo de ENVIO (XML)", type=["xml"], help="O arquivo que você enviou para a operadora")
    file_retorno = st.file_uploader("Arquivo de RETORNO (XML)", type=["xml"], help="O arquivo de demonstrativo que a operadora te devolveu")

if file_envio and file_retorno:
    with st.sidebar:
        st.header("Configurações")
        lote_id, lista_guias = extrair_metadados(file_retorno)
        
        if lote_id == "Erro":
            st.error("Não foi possível ler as guias do arquivo de retorno.")
        else:
            st.info(f"Lote: {lote_id}")
            selecionadas = st.multiselect(
                "Filtrar Guias:",
                options=lista_guias,
                default=lista_guias,
                help="Selecione apenas as guias que devem aparecer no resultado final."
            )

    with col2:
        st.subheader("2. Processamento")
        if st.button("🚀 Gerar Novo XML Corrigido", use_container_width=True):
            if not selecionadas:
                st.warning("Selecione pelo menos uma guia na barra lateral.")
            else:
                try:
                    with st.spinner("Cruzando dados e corrigindo datas..."):
                        # Resetar ponteiros dos arquivos para o início
                        file_envio.seek(0)
                        file_retorno.seek(0)
                        
                        # Chama a função com o nome correto: processar_xmls
                        resultado_xml = processar_xmls(file_envio, file_retorno, selecionadas)
                        
                        if isinstance(resultado_xml, str) and resultado_xml.startswith("Erro"):
                            st.error(resultado_xml)
                        else:
                            st.success("XML gerado com sucesso!")
                            st.download_button(
                                label="💾 Baixar XML Corrigido",
                                data=resultado_xml,
                                file_name=f"DEMONSTRATIVO_CORRIGIDO_{lote_id}.xml",
                                mime="application/xml",
                                use_container_width=True
                            )
                except Exception as e:
                    st.error(f"Ocorreu um erro inesperado: {e}")
else:
    with col2:
        st.info("Aguardando o upload dos dois arquivos XML para iniciar...")

st.markdown("---")
st.caption("Versão 1.0 - Ajuste automático de datas SADT e Glosas Amazônia")
