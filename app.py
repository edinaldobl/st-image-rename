import streamlit as st
import os
import tempfile
import zipfile
from PIL import Image
import pandas as pd
import logging
from datetime import datetime
import io
from typing import Dict, List, Tuple, Optional
import platform

# Configuração da página
st.set_page_config(
    page_title="Renomear Imagens com CSV",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

class ImageProcessor:
    def __init__(self):
        self.valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
        self.log_messages = []
    
    def log(self, message: str, level: str = "INFO"):
        """Adiciona mensagem ao log interno"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {level} - {message}"
        self.log_messages.append(log_entry)
        
    def is_image_file(self, filename: str) -> bool:
        """Verifica se o arquivo é uma imagem válida."""
        return filename.lower().endswith(self.valid_extensions)
    
    def load_sku_mapping(self, csv_file) -> Dict[str, str]:
        """Carrega o mapeamento SKU a partir do CSV."""
        encodings = ['utf-8', 'latin1', 'cp1252']
        for encoding in encodings:
            try:
                csv_file.seek(0)  # Reseta o ponteiro do arquivo
                df = pd.read_csv(csv_file, encoding=encoding)
                if 'CÓDIGO' not in df.columns or 'SKU' not in df.columns:
                    self.log("CSV não contém as colunas 'CÓDIGO' e 'SKU'", "ERROR")
                    return {}
                df = df.dropna(subset=['CÓDIGO', 'SKU'])
                df['CÓDIGO'] = df['CÓDIGO'].astype(str).str.strip()
                df['SKU'] = df['SKU'].astype(str).str.strip()
                mapping = df.set_index('CÓDIGO')['SKU'].to_dict()
                self.log(f"Mapeamento SKU carregado com {len(mapping)} registros (codificação: {encoding})")
                return mapping
            except Exception as e:
                self.log(f"Tentativa com codificação {encoding} falhou: {str(e)}", "WARNING")
                continue
        self.log("Nenhuma codificação funcionou para ler o CSV", "ERROR")
        return {}
    
    def get_image_files_from_folder(self, folder_path: str) -> List[str]:
        """Retorna uma lista de arquivos de imagem em todas as subpastas, limitada a 6 por subpasta."""
        image_files = []
        if not os.path.exists(folder_path):
            self.log(f"Pasta não encontrada: {folder_path}", "ERROR")
            return image_files
            
        for root, _, files in os.walk(folder_path):
            image_count = 0
            for file in files:
                if self.is_image_file(file):
                    image_files.append(os.path.join(root, file))
                    image_count += 1
                    if image_count >= 6:
                        break
        return image_files
    
    def process_folder_images(self, source_folder: str, destination_folder: str, sku_mapping: Dict[str, str]) -> Tuple[Dict[str, List[str]], int, int, List[str]]:
        """Processa imagens de uma pasta local."""
        code_to_images = {}
        current_code = None
        image_index = 1
        failed_items = []
        total_files = 0
        successful_files = 0
        
        if not os.path.exists(destination_folder):
            try:
                os.makedirs(destination_folder)
                self.log(f"Pasta de destino criada: {destination_folder}")
            except Exception as e:
                self.log(f"Erro ao criar pasta de destino: {str(e)}", "ERROR")
                return code_to_images, 0, 0, []
        
        image_files = self.get_image_files_from_folder(source_folder)
        total_files = len(image_files)
        
        if not image_files:
            self.log("Nenhuma imagem encontrada na pasta de origem", "WARNING")
            return code_to_images, 0, 0, []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, image_path in enumerate(image_files):
            try:
                progress = (idx + 1) / len(image_files)
                progress_bar.progress(progress)
                status_text.text(f"Processando: {os.path.basename(image_path)}")
                
                filename = os.path.basename(image_path)
                name, ext = os.path.splitext(filename)
                ext = ext.lower()
                
                code = name[:5]
                
                if current_code != code:
                    current_code = code
                    image_index = 1
                
                if code in sku_mapping:
                    sku = sku_mapping[code]
                    new_filename = f"{sku}_{code}_{image_index:02d}{ext}"
                    destination_path = os.path.join(destination_folder, new_filename)
                    
                    with Image.open(image_path) as img:
                        if ext not in ['.jpg', '.jpeg']:
                            img = img.convert('RGB')
                            ext = '.jpg'
                            new_filename = f"{sku}_{code}_{image_index:02d}.jpg"
                            destination_path = os.path.join(destination_folder, new_filename)
                        
                        img.save(destination_path, 'JPEG' if ext == '.jpg' else ext[1:].upper(), quality=95)
                    
                    if code in code_to_images:
                        code_to_images[code].append(new_filename)
                    else:
                        code_to_images[code] = [new_filename]
                    
                    image_index += 1
                    if image_index > 6:
                        image_index = 1
                    
                    successful_files += 1
                    self.log(f"Processado: {filename} -> {new_filename}")
                else:
                    self.log(f"Código {code} não encontrado no CSV, ignorando {filename}", "WARNING")
                    failed_items.append(filename)
            
            except Exception as e:
                self.log(f"Erro ao processar {image_path}: {str(e)}", "ERROR")
                failed_items.append(filename)
                continue
        
        progress_bar.progress(1.0)
        status_text.text("Processamento concluído!")
        
        return code_to_images, total_files, len(failed_items), failed_items

    def process_zip_images(self, zip_file, sku_mapping: Dict[str, str]) -> Tuple[Dict[str, List[str]], int, int, List[str], bytes]:
        """Processa imagens de um arquivo ZIP."""
        code_to_images = {}
        current_code = None
        image_index = 1
        failed_items = []
        total_files = 0
        successful_files = 0
        
        output_zip = io.BytesIO()
        
        try:
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                image_files = [f for f in zip_ref.namelist() if self.is_image_file(f) and not f.startswith('__MACOSX/')]
                total_files = len(image_files)
                
                folder_counts = {}
                filtered_files = []
                
                for file_path in image_files:
                    folder = os.path.dirname(file_path)
                    if folder not in folder_counts:
                        folder_counts[folder] = 0
                    
                    if folder_counts[folder] < 6:
                        filtered_files.append(file_path)
                        folder_counts[folder] += 1
                
                with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as output_zip_ref:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for idx, file_path in enumerate(filtered_files):
                        try:
                            progress = (idx + 1) / len(filtered_files)
                            progress_bar.progress(progress)
                            status_text.text(f"Processando: {os.path.basename(file_path)}")
                            
                            filename = os.path.basename(file_path)
                            name, ext = os.path.splitext(filename)
                            ext = ext.lower()
                            
                            code = name[:5]
                            
                            if current_code != code:
                                current_code = code
                                image_index = 1
                            
                            if code in sku_mapping:
                                sku = sku_mapping[code]
                                new_filename = f"{sku}_{code}_{image_index:02d}{ext}"
                                
                                with zip_ref.open(file_path) as image_file:
                                    image_data = image_file.read()
                                    
                                    with Image.open(io.BytesIO(image_data)) as img:
                                        if ext not in ['.jpg', '.jpeg']:
                                            img = img.convert('RGB')
                                            ext = '.jpg'
                                            new_filename = f"{sku}_{code}_{image_index:02d}.jpg"
                                        
                                        img_bytes = io.BytesIO()
                                        img.save(img_bytes, 'JPEG' if ext == '.jpg' else ext[1:].upper(), quality=95)
                                        output_zip_ref.writestr(new_filename, img_bytes.getvalue())
                                
                                if code in code_to_images:
                                    code_to_images[code].append(new_filename)
                                else:
                                    code_to_images[code] = [new_filename]
                                
                                image_index += 1
                                if image_index > 6:
                                    image_index = 1
                                
                                successful_files += 1
                                self.log(f"Processado: {filename} -> {new_filename}")
                            else:
                                self.log(f"Código {code} não encontrado no CSV, ignorando {filename}", "WARNING")
                                failed_items.append(filename)
                        
                        except Exception as e:
                            self.log(f"Erro ao processar {file_path}: {str(e)}", "ERROR")
                            failed_items.append(filename)
                            continue
                    
                    progress_bar.progress(1.0)
                    status_text.text("Processamento concluído!")
        
        except Exception as e:
            self.log(f"Erro geral ao processar ZIP: {str(e)}", "ERROR")
        
        return code_to_images, total_files, len(failed_items), failed_items, output_zip.getvalue()
    
    def create_result_csv(self, original_csv, code_to_images: Dict[str, List[str]]) -> bytes:
        """Cria um novo CSV com a coluna de nomes de imagens."""
        try:
            original_csv.seek(0)  # Reseta o ponteiro do arquivo
            df = pd.read_csv(original_csv, encoding='utf-8')
            df['CÓDIGO'] = df['CÓDIGO'].astype(str).str.strip().fillna('')
            df['IMAGENS'] = df['CÓDIGO'].apply(
                lambda x: ', '.join(code_to_images.get(x[:5], [])) if x[:5] in code_to_images else ''
            )
            output = io.StringIO()
            df.to_csv(output, index=False, encoding='utf-8')
            return output.getvalue().encode('utf-8')
        except Exception as e:
            self.log(f"Erro ao criar CSV de resultado: {str(e)}", "ERROR")
            return b""

def main():
    # Título principal
    st.title("🪄 Processador de Imagens com SKU")
    st.markdown("Converta e organize imagens com base em códigos e SKUs de forma eficiente.")

    # Inicializa o processador
    if 'processor' not in st.session_state:
        st.session_state.processor = ImageProcessor()
    
    processor = st.session_state.processor
    
    # Define exemplos de caminhos baseados no sistema operacional
    system = platform.system()
    if system == "Windows":
        source_placeholder = "C:\\Users\\SeuNome\\Imagens"
        dest_placeholder = "C:\\Users\\SeuNome\\Imagens_Processadas"
    elif system == "Darwin":  # macOS
        source_placeholder = "/Users/SeuNome/Pictures"
        dest_placeholder = "/Users/SeuNome/Desktop/Imagens_Processadas"
    else:  # Linux ou outros
        source_placeholder = "/home/seunome/imagens"
        dest_placeholder = "/home/seunome/imagens_processadas"
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configurações")
        
        # Seleção do método de entrada
        st.subheader("📥 Método de Entrada")
        processing_method = st.radio(
            "Escolha como fornecer as imagens:",
            ["📁 Pastas Locais", "📦 Arquivo ZIP"],
            help="Selecione 'Pastas Locais' para processar imagens de diretórios ou 'Arquivo ZIP' para upload de um arquivo compactado."
        )
        
        st.markdown("---")
        
        # Upload do CSV
        st.subheader("📄 Arquivo CSV")
        csv_file = st.file_uploader(
            "Carregar CSV com SKUs",
            type=['csv'],
            help="O CSV deve conter as colunas 'CÓDIGO' e 'SKU'."
        )
        
        csv_valid = False
        if csv_file:
            try:
                csv_file.seek(0)  # Reseta o ponteiro
                df_preview = pd.read_csv(csv_file, encoding='utf-8')
                st.success(f"✅ CSV carregado: {len(df_preview)} registros")
                
                with st.expander("👀 Visualizar CSV"):
                    st.dataframe(df_preview.head(10))
                
                if 'CÓDIGO' not in df_preview.columns:
                    st.error("❌ Coluna 'CÓDIGO' não encontrada no CSV")
                elif 'SKU' not in df_preview.columns:
                    st.error("❌ Coluna 'SKU' não encontrada no CSV")
                elif df_preview['CÓDIGO'].isna().all():
                    st.error("❌ Coluna 'CÓDIGO' contém apenas valores nulos")
                else:
                    csv_valid = True
                    # Verifica se os códigos têm pelo menos 5 caracteres
                    df_preview['CÓDIGO'] = df_preview['CÓDIGO'].astype(str).str.strip()
                    if df_preview['CÓDIGO'].str.len().min() < 5:
                        st.warning("⚠️ Alguns códigos têm menos de 5 caracteres, o que pode causar falhas no mapeamento")
            except Exception as e:
                st.error(f"❌ Erro ao ler o CSV: {str(e)}")
                csv_valid = False
        
        st.markdown("---")
        
        # Configurações de entrada (Pastas ou ZIP)
        if processing_method == "📁 Pastas Locais":
            st.subheader("📂 Seleção de Pastas")
            
            st.markdown("""
            **Como selecionar pastas:**
            1. Abra o explorador de arquivos.
            2. Navegue até a pasta desejada.
            3. Clique com o botão direito na pasta e selecione 'Copiar caminho' (ou similar).
            4. Cole o caminho no campo abaixo.
            """)
            
            source_folder = st.text_input(
                "Pasta de Origem",
                placeholder=source_placeholder,
                help=f"Cole o caminho completo da pasta com as imagens. Exemplo: {source_placeholder}"
            )
            
            if source_folder:
                if os.path.exists(source_folder):
                    image_files = processor.get_image_files_from_folder(source_folder)
                    st.success(f"✅ {len(image_files)} imagens encontradas")
                    
                    subfolders = set()
                    for img_path in image_files:
                        relative_path = os.path.relpath(img_path, source_folder)
                        subfolder = os.path.dirname(relative_path)
                        if subfolder and subfolder != '.':
                            subfolders.add(subfolder)
                    
                    if subfolders:
                        with st.expander("📁 Subpastas"):
                            for subfolder in sorted(subfolders):
                                subfolder_path = os.path.join(source_folder, subfolder)
                                subfolder_images = [f for f in image_files if f.startswith(subfolder_path)]
                                st.text(f"📁 {subfolder}: {len(subfolder_images)} imagens")
                else:
                    st.error("❌ Pasta não encontrada. Verifique o caminho.")
            
            destination_folder = st.text_input(
                "Pasta de Destino",
                placeholder=dest_placeholder,
                help=f"Cole o caminho onde as imagens processadas serão salvas. Exemplo: {dest_placeholder}"
            )
            
            if destination_folder:
                if os.path.exists(destination_folder):
                    st.success("✅ Pasta de destino válida")
                else:
                    st.info("ℹ️ Pasta será criada durante o processamento")
            
            # Botão para verificar pastas
            if source_folder or destination_folder:
                if st.button("🔍 Verificar Pastas", use_container_width=True):
                    if source_folder and not os.path.exists(source_folder):
                        st.error("❌ Pasta de origem inválida")
                    elif not source_folder:
                        st.warning("⚠️ Informe a pasta de origem")
                    if destination_folder and os.path.exists(destination_folder):
                        st.success("✅ Pasta de destino válida")
                    elif not destination_folder:
                        st.warning("⚠️ Informe a pasta de destino")
                    if source_folder and os.path.exists(source_folder) and destination_folder:
                        st.success("✅ Ambas as pastas estão prontas!")
            
            source_ready = source_folder and os.path.exists(source_folder)
            dest_ready = destination_folder
            zip_file = None
            
        else:
            st.subheader("📦 Arquivo ZIP")
            zip_file = st.file_uploader(
                "Carregar arquivo ZIP",
                type=['zip'],
                help="ZIP com imagens organizadas em pastas (máx. 6 por pasta)."
            )
            
            if zip_file:
                try:
                    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                        files = [f for f in zip_ref.namelist() 
                                if processor.is_image_file(f) and not f.startswith('__MACOSX/')]
                        st.success(f"✅ {len(files)} imagens encontradas")
                        
                        folders = set(os.path.dirname(f) for f in files if os.path.dirname(f))
                        if folders:
                            with st.expander("📁 Estrutura do ZIP"):
                                for folder in sorted(folders):
                                    folder_files = [f for f in files if f.startswith(folder)]
                                    st.text(f"📁 {folder}: {len(folder_files)} imagens")
                                    
                except Exception as e:
                    st.error(f"❌ Erro ao ler o ZIP: {str(e)}")
            
            source_ready = zip_file is not None
            dest_ready = True
            source_folder = None
            destination_folder = None
        
        st.markdown("---")
        
        # Botão de processamento
        if csv_valid and source_ready and dest_ready:
            if st.button("🚀 Processar Imagens", type="primary", use_container_width=True):
                with st.spinner("Processando imagens..."):
                    sku_mapping = processor.load_sku_mapping(csv_file)
                    
                    if not sku_mapping:
                        st.error("❌ Falha ao carregar o mapeamento do CSV. Verifique o arquivo e tente novamente.")
                        st.info("Certifique-se de que o CSV contém as colunas 'CÓDIGO' e 'SKU', está codificado em UTF-8, e que os códigos têm pelo menos 5 caracteres.")
                        return
                    
                    if processing_method == "📁 Pastas Locais":
                        code_to_images, total_files, failures, failed_items = processor.process_folder_images(
                            source_folder, destination_folder, sku_mapping
                        )
                        
                        result_csv_data = processor.create_result_csv(csv_file, code_to_images)
                        if result_csv_data:
                            result_csv_path = os.path.join(destination_folder, f"resultado_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
                            with open(result_csv_path, 'wb') as f:
                                f.write(result_csv_data)
                            processor.log(f"CSV resultado salvo em: {result_csv_path}")
                        
                        st.session_state.results = {
                            'method': 'folders',
                            'code_to_images': code_to_images,
                            'total_files': total_files,
                            'failures': failures,
                            'failed_items': failed_items,
                            'successful_files': total_files - failures,
                            'destination_folder': destination_folder,
                            'result_csv_path': result_csv_path if result_csv_data else None
                        }
                    else:
                        code_to_images, total_files, failures, failed_items, processed_zip = processor.process_zip_images(
                            zip_file, sku_mapping
                        )
                        
                        result_csv = processor.create_result_csv(csv_file, code_to_images)
                        
                        st.session_state.results = {
                            'method': 'zip',
                            'code_to_images': code_to_images,
                            'total_files': total_files,
                            'failures': failures,
                            'failed_items': failed_items,
                            'processed_zip': processed_zip,
                            'result_csv': result_csv,
                            'successful_files': total_files - failures
                        }
        else:
            missing_items = []
            if not csv_valid:
                missing_items.append("📄 Arquivo CSV válido")
            if not source_ready:
                missing_items.append("📁 Pasta de origem" if processing_method == "📁 Pastas Locais" else "📦 Arquivo ZIP")
            if not dest_ready and processing_method == "📁 Pastas Locais":
                missing_items.append("📁 Pasta de destino")
            
            if missing_items:
                st.warning(f"⚠️ **Faltando:** {' | '.join(missing_items)}")

    # Corpo principal
    st.markdown("---")
    st.header("🗂️ Resultados do Processamento")
    
    if 'results' in st.session_state:
        results = st.session_state.results
        
        # Métricas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📁 Total de Imagens", results['total_files'])
        with col2:
            st.metric("✅ Processadas", results['successful_files'])
        with col3:
            st.metric("❌ Falhas", results['failures'])
        with col4:
            success_rate = (results['successful_files'] / results['total_files'] * 100) if results['total_files'] > 0 else 0
            st.metric("📈 Taxa de Sucesso", f"{success_rate:.1f}%")
        
        # Informações de salvamento ou downloads
        st.markdown("---")
        st.subheader("💾 Arquivos Gerados")
        
        if results['method'] == 'folders':
            st.success(f"✅ Imagens salvas em: `{results['destination_folder']}`")
            if results.get('result_csv_path'):
                st.success(f"✅ CSV resultado salvo em: `{results['result_csv_path']}`")
        else:
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                if results.get('processed_zip'):
                    st.download_button(
                        label="📦 Baixar Imagens Processadas (ZIP)",
                        data=results['processed_zip'],
                        file_name=f"imagens_processadas_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
            with col_dl2:
                if results.get('result_csv'):
                    st.download_button(
                        label="📄 Baixar CSV Resultado",
                        data=results['result_csv'],
                        file_name=f"resultado_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
        
        # Detalhes do processamento
        with st.expander("📋 Log de Processamento"):
            for log_msg in processor.log_messages:
                if "ERROR" in log_msg:
                    st.error(log_msg)
                elif "WARNING" in log_msg:
                    st.warning(log_msg)
                else:
                    st.text(log_msg)
        
        if results['failed_items']:
            with st.expander("❌ Itens com Falha"):
                for item in results['failed_items']:
                    st.text(f"• {item}")
    else:
        st.info("ℹ️ Aguardando processamento...")

if __name__ ==
 "__main__":
    main()
