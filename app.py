import streamlit as st
import xml.etree.ElementTree as ET
from processador import processar_xmls # Importa sua lógica v14

# Configuração da página
st.set_page_config(page_title="Gerador de Demonstrativo TISS", layout="centered")

st.title("Gerador de Demonstrativo de Retorno")

# Estilização básica para parecer com sua imagem
st.markdown("""
    <style>
    .stButton button { width: 100%; border-radius: 20px; height: 3em; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

# Colunas para os Uploads (Parte de cima da sua imagem)
col1, col2 = st.columns(2)

with col1:
    arquivo_envio = st.file_uploader("ENVIE SEU XML DE ENVIO", type=["xml"])

with col2:
    arquivo_retorno = st.file_uploader("ENVIE SEU XML DE RETORNO", type=["xml"])

# Botão de Gerar (Centro da imagem)
if st.button("CLIQUE AQUI PARA GERAR"):
    if arquivo_envio and arquivo_retorno:
        try:
            # Chama a função que processa os dados
            xml_gerado = processar_xmls(arquivo_envio, arquivo_retorno)
            
            st.success("XML Processado com Sucesso!")
            
            # Botão de Download (Parte de baixo da imagem)
            st.download_button(
                label="CLIQUE AQUI PARA BAIXAR SEU XML GERADO",
                data=xml_gerado,
                file_name="DEMONSTRATIVO_GERADO.xml",
                mime="application/xml"
            )
        except Exception as e:
            st.error(f"Erro ao processar: {e}")
    else:
        st.warning("Por favor, anexe ambos os arquivos antes de gerar.")
