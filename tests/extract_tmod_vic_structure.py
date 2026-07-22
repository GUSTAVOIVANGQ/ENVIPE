import os
import glob
import zipfile
import csv

def parse_dbf_fields_from_file_obj(f):
    fields = []
    header = f.read(32)
    if len(header) < 32: 
        return fields
    
    while True:
        field_desc = f.read(32)
        if len(field_desc) < 32 or field_desc[0] == 0x0D:
            break
        
        name = field_desc[0:11].split(b'\x00')[0].decode('ascii', errors='ignore')
        ftype = chr(field_desc[11])
        flen = field_desc[16]
        fdec = field_desc[17]
        
        fields.append({"name": name, "type": ftype, "length": flen, "decimals": fdec})
        
    return fields

def process_zips(directory):
    results = []
    zip_files = glob.glob(os.path.join(directory, '*.zip'))
    
    for zip_path in sorted(zip_files):
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                # find TMod_Vic.dbf
                for name in z.namelist():
                    if 'tmod_vic' in name.lower() and name.lower().endswith('.dbf'):
                        with z.open(name) as f:
                            fields = parse_dbf_fields_from_file_obj(f)
                            for field in fields:
                                results.append({
                                    "zip_file": os.path.basename(zip_path),
                                    "dbf_file": name,
                                    "field_name": field["name"],
                                    "field_type": field["type"],
                                    "field_length": field["length"],
                                    "field_decimals": field["decimals"]
                                })
        except Exception as e:
            print(f"Error processing {zip_path}: {e}")
            
    return results

if __name__ == '__main__':
    data_dir = r"C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\conjunto_de_datos"
    output_csv = r"C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\estructura_tmod_vic.csv"
    
    print("Iniciando extracción de estructuras...")
    data = process_zips(data_dir)
    
    if data:
        keys = ["zip_file", "dbf_file", "field_name", "field_type", "field_length", "field_decimals"]
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
        print(f"Estructura guardada en: {output_csv}")
    else:
        print("No se encontraron archivos TMod_Vic.dbf o no se pudo extraer información.")
