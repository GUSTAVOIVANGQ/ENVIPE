import os
import zipfile

def listar_archivos_y_zips(directorio):
    """
    Recorre el directorio dado y muestra todos sus archivos, carpetas,
    y el contenido de los archivos .zip.
    """
    if not os.path.exists(directorio):
        print(f"El directorio no existe: {directorio}")
        return

    for root, dirs, files in os.walk(directorio):
        print(f"\nDirectorio actual: {root}")
        
        for dir_name in dirs:
            print(f"  [Carpeta] {dir_name}")
            
        for file_name in files:
            print(f"  [Archivo] {file_name}")
            
            # Si el archivo es un zip, listar su contenido
            if file_name.lower().endswith('.zip'):
                zip_path = os.path.join(root, file_name)
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        print(f"    [Contenido ZIP] {file_name}:")
                        for info in zip_ref.infolist():
                            # El nombre del archivo dentro del zip incluye su ruta interna
                            if info.is_dir():
                                print(f"      [Carpeta Interna] {info.filename}")
                            else:
                                print(f"      [Archivo Interno] {info.filename}")
                except zipfile.BadZipFile:
                    print(f"    [Error] El archivo {file_name} está corrupto o no es un zip válido.")
                except Exception as e:
                    print(f"    [Error] No se pudo leer {file_name}: {e}")

if __name__ == "__main__":
    directorio_objetivo = r"C:\Users\ivan-\Documents\GitHub\ENVIPE\conjunto_de_datos"
    print(f"Analizando: {directorio_objetivo}")
    listar_archivos_y_zips(directorio_objetivo)
