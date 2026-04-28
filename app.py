import streamlit as st
from io import BytesIO
from processador import processar_xmls, extrair_lotes_guias

# ── Configuração da página ──────────────────────────────────────────────────
st.set_page_config(page_title="Gerador de Demonstrativo TISS", layout="centered")

st.markdown("""
<style>
/* Botão principal */
div.stButton > button {
    width: 100%;
    border-radius: 20px;
    height: 3em;
    font-weight: bold;
}
/* Botão de download */
div.stDownloadButton > button {
    width: 100%;
    border-radius: 20px;
    height: 3em;
    font-weight: bold;
    background-color: #1a1a2e;
    color: white;
}
/* Separa visualmente a seção de seleção */
.secao-selecao {
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid #333;
}
</style>
""", unsafe_allow_html=True)

st.title("Gerador de Demonstrativo de Retorno")

# ── Upload dos arquivos ────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    arquivo_envio = st.file_uploader("ENVIE SEU XML DE ENVIO", type=["xml"])
with col2:
    arquivo_retorno = st.file_uploader("ENVIE SEU XML DE RETORNO", type=["xml"])


# ── Callbacks de "selecionar todos" ────────────────────────────────────────
def toggle_todos_lotes():
    novo_val = st.session_state.get("cb_todos_lotes", True)
    for lote in st.session_state.get("lista_lotes", []):
        st.session_state[f"cb_lote_{lote}"] = novo_val

def toggle_todos_guias():
    novo_val = st.session_state.get("cb_todos_guias", True)
    for guia in st.session_state.get("lista_guias_visiveis", []):
        st.session_state[f"cb_guia_{guia}"] = novo_val


# ── Botão de leitura dos XMLs ───────────────────────────────────────────────
if st.button("CLIQUE AQUI PARA GERAR"):
    if arquivo_envio and arquivo_retorno:
        try:
            arquivo_envio.seek(0)
            dados = extrair_lotes_guias(arquivo_envio)

            if not dados:
                st.error("Nenhum lote encontrado no XML de envio.")
            else:
                # Guarda bytes para reuso posterior (evita problema de stream já lido)
                arquivo_envio.seek(0)
                arquivo_retorno.seek(0)
                st.session_state["bytes_envio"] = arquivo_envio.read()
                st.session_state["bytes_retorno"] = arquivo_retorno.read()
                st.session_state["dados_lotes"] = dados

                # Inicializa checkboxes como True (todos selecionados)
                lotes = list(dados.keys())
                st.session_state["lista_lotes"] = lotes
                for lote in lotes:
                    if f"cb_lote_{lote}" not in st.session_state:
                        st.session_state[f"cb_lote_{lote}"] = True

                todas_guias = [g for gs in dados.values() for g in gs]
                st.session_state["lista_guias_visiveis"] = todas_guias
                for guia in todas_guias:
                    if f"cb_guia_{guia}" not in st.session_state:
                        st.session_state[f"cb_guia_{guia}"] = True

                st.session_state["xml_gerado"] = None  # limpa download anterior

        except Exception as e:
            st.error(f"Erro ao ler XML de envio: {e}")
    else:
        st.warning("Por favor, anexe ambos os arquivos antes de gerar.")


# ── Seção de seleção de Lotes e Guias ──────────────────────────────────────
if "dados_lotes" in st.session_state:
    dados = st.session_state["dados_lotes"]
    lotes = st.session_state.get("lista_lotes", list(dados.keys()))

    st.markdown('<div class="secao-selecao"></div>', unsafe_allow_html=True)

    col_l, col_g = st.columns(2)

    # ── Coluna LOTES ──
    with col_l:
        st.markdown("#### LOTES")
        st.checkbox(
            "selecionar todos",
            key="cb_todos_lotes",
            value=True,
            on_change=toggle_todos_lotes,
        )
        lotes_selecionados = []
        for lote in lotes:
            if f"cb_lote_{lote}" not in st.session_state:
                st.session_state[f"cb_lote_{lote}"] = True
            st.checkbox(lote, key=f"cb_lote_{lote}")
            if st.session_state[f"cb_lote_{lote}"]:
                lotes_selecionados.append(lote)

    # ── Coluna GUIAS (exibe só guias dos lotes selecionados) ──
    with col_g:
        st.markdown("#### GUIAS")

        # Recalcula quais guias mostrar com base nos lotes marcados
        guias_visiveis = []
        for lote in lotes_selecionados:
            for guia in dados.get(lote, []):
                if guia not in guias_visiveis:
                    guias_visiveis.append(guia)
        st.session_state["lista_guias_visiveis"] = guias_visiveis

        if guias_visiveis:
            st.checkbox(
                "selecionar todos",
                key="cb_todos_guias",
                value=True,
                on_change=toggle_todos_guias,
            )
            guias_selecionadas = []
            for guia in guias_visiveis:
                if f"cb_guia_{guia}" not in st.session_state:
                    st.session_state[f"cb_guia_{guia}"] = True
                st.checkbox(guia, key=f"cb_guia_{guia}")
                if st.session_state[f"cb_guia_{guia}"]:
                    guias_selecionadas.append(guia)
        else:
            st.info("Selecione ao menos um lote para ver as guias.")
            guias_selecionadas = []

    st.markdown("---")

    # ── Botão de geração final ──────────────────────────────────────────────
    if st.button("GERAR XML FINAL", type="primary"):
        if not lotes_selecionados:
            st.warning("Selecione ao menos um lote.")
        elif not guias_selecionadas:
            st.warning("Selecione ao menos uma guia.")
        else:
            try:
                env_bytes = BytesIO(st.session_state["bytes_envio"])
                ret_bytes = BytesIO(st.session_state["bytes_retorno"])

                xml_gerado = processar_xmls(
                    env_bytes,
                    ret_bytes,
                    lotes_filtro=lotes_selecionados,
                    guias_filtro=guias_selecionadas,
                )
                st.session_state["xml_gerado"] = xml_gerado
                st.success(
                    f"XML gerado com sucesso! "
                    f"({len(lotes_selecionados)} lote(s), {len(guias_selecionadas)} guia(s))"
                )
            except Exception as e:
                st.error(f"Erro ao processar: {e}")

    # Mantém o botão de download persistente após geração
    if st.session_state.get("xml_gerado"):
        st.download_button(
            label="⬇ CLIQUE AQUI PARA BAIXAR SEU XML GERADO",
            data=st.session_state["xml_gerado"],
            file_name="DEMONSTRATIVO_GERADO.xml",
            mime="application/xml",
        )
