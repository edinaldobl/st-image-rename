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
from tkinter import Tk, filedialog

# Configuração da página
st.set_page_config(
    page_title="Renomear Imagens com CSV",
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

def select_folder(prompt: str) -> str:
    """Abre uma janela para selecionar uma pasta usando tkinter."""
    root = Tk()
    root.withdraw()  # Esconde a janela principal
    folder = filedialog.askdirectory(title=prompt)
    root.destroy()
    return folder

def main():
