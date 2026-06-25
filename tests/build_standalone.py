import os

base_dir = r"C:\Users\ivan-\Documents\GitHub\ENVIPE"
html_path = os.path.join(base_dir, "ENVIPE — Delitos por Medio de Comisión_files", "ENVIPE — Delitos por Medio de Comisión.html")
chart_js_path = os.path.join(base_dir, "ENVIPE — Delitos por Medio de Comisión_files", "chart.umd.min.js.download")
data_js_path = os.path.join(base_dir, "ENVIPE — Delitos por Medio de Comisión_files", "dashboard_data.js")
out_path = os.path.join(base_dir, "ENVIPE_Dashboard_Standalone.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

with open(chart_js_path, "r", encoding="utf-8") as f:
    chart_js_content = f.read()

with open(data_js_path, "r", encoding="utf-8") as f:
    data_js_content = f.read()

# Reemplazar scripts externos por código inline
chart_tag = '<script src="./ENVIPE — Delitos por Medio de Comisión_files/chart.umd.min.js.download"></script>'
data_tag = '<script src="./ENVIPE — Delitos por Medio de Comisión_files/dashboard_data.js"></script>'

html_content = html_content.replace(chart_tag, f'<script>\n{chart_js_content}\n</script>')
html_content = html_content.replace(data_tag, f'<script>\n{data_js_content}\n</script>')

with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Archivo standalone generado exitosamente en: {out_path}")
