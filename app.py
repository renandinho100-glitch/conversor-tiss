import streamlit as st
from processador import extrair_metadados, gerar_xml_final # Importa do outro arquivo

st.set_page_config(page_title="Processador TISS", layout="wide")

st.title("🚀 Processador de Retorno TISS")
st.markdown("Selecione os arquivos e escolha as guias que deseja processar.")

col1, col2 = st.columns(2)

with col1:
    file_envio = st.file_uploader("Arquivo de ENVIO (XML)", type=["xml"])
with col2:
    file_retorno = st.file_uploader("Arquivo de RETORNO (XML)", type=["xml"])

if file_envio and file_retorno:
    # Busca as guias disponíveis no retorno para mostrar na tela
    lote_id, lista_guias = extrair_metadados(file_retorno)
    
    st.subheader(f"Lote identificado: {lote_id}")
    
    # Checkbox para selecionar as guias
    selecionadas = st.multiselect(
        "Selecione as guias que deseja manter no novo XML:",
        options=lista_guias,
        default=lista_guias
    )

    if st.button("Gerar Novo XML"):
        if not selecionadas:
            st.error("Selecione pelo menos uma guia!")
        else:
            with st.spinner("Processando..."):
                # Volta o ponteiro do arquivo para o início (necessário para o Streamlit)
                file_envio.seek(0)
                file_retorno.seek(0)
                
                resultado_xml = gerar_xml_final(file_envio, file_retorno, selecionadas)
                
                st.success("XML gerado com sucesso!")
                st.download_button(
                    label="Baixar XML Corrigido",
                    data=resultado_xml,
                    file_name=f"RETORNO_PROCESSADO_{lote_id}.xml",
                    mime="application/xml"
                )
else:
    st.info("Aguardando upload dos arquivos para listar as guias.")
