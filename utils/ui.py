import os
import json
import logging
import streamlit as st

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def inject_custom_css():
    st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=Outfit:wght@400;700;900&display=swap');
    
    html, body, [class*="css"]  {
        font-family: 'Inter', sans-serif;
    }
    .main-title {
        font-family: 'Outfit', sans-serif;
        font-size: 2.5rem;
        font-weight: 900;
        background: linear-gradient(135deg, #059669, #2563eb);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
        animation: fadeIn 1s ease-in-out;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1rem;
        color: #6b7280;
        margin-bottom: 1.5rem;
    }
    
    /* Glassmorphism containers */
    .glass-container {
        background: rgba(255, 255, 255, 0.7);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.05);
        margin-bottom: 1.5rem;
    }
    
    /* ANVISA Table Enhancements */
    .anvisa-table-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        border: 2px solid #111111;
        max-width: 420px;
        margin: 0 auto;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        transition: transform 0.3s ease;
    }
    .anvisa-table-container:hover {
        transform: translateY(-2px);
    }
    .anvisa-table {
        width: 100%;
        border-collapse: collapse;
        color: #000000 !important;
        font-family: 'Arial', sans-serif;
        font-size: 11px;
    }
    .anvisa-table th, .anvisa-table td {
        border: 1px solid #000000;
        padding: 4px 6px;
        text-align: left;
        color: #000000 !important;
    }
    .anvisa-table td.num {
        text-align: right;
    }
    .anvisa-table tr.header-row th {
        font-size: 13px;
        font-weight: bold;
        text-align: center;
        border-bottom: 2px solid #000000;
    }
    .anvisa-table tr.sub-header-row td {
        font-weight: bold;
        background-color: #f3f4f6;
    }
    .anvisa-table tr.indent-row td.name {
        padding-left: 15px;
    }
    
    /* Buttons */
    .stButton>button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        transform: scale(1.02);
    }
    
    .legal-box {
        background-color: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1rem;
        margin-top: 1rem;
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
    }
</style>
    """, unsafe_allow_html=True)


def generate_anvisa_lupa_svg(alto_acucar, alto_gordura, alto_sodio):
    active_nutrients = []
    if alto_acucar:
        active_nutrients.append("AÇÚCAR ADICIONADO")
    if alto_gordura:
        active_nutrients.append("GORDURA SATURADA")
    if alto_sodio:
        active_nutrients.append("SÓDIO")
        
    num_nutrients = len(active_nutrients)
    if num_nutrients == 0:
        return ""
        
    width = 180
    height = 15 + 45 + (num_nutrients * 60)
    
    svg = f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
    svg += f'<rect x="4" y="4" width="{width - 8}" height="{height - 8}" rx="15" ry="15" stroke="black" stroke-width="4" fill="white" />'
    svg += '<rect x="15" y="15" width="150" height="38" rx="19" ry="19" stroke="black" stroke-width="4" fill="white" />'
    svg += '<circle cx="36" cy="34" r="12" stroke="black" stroke-width="4" fill="white" />'
    svg += '<line x1="28" y1="42" x2="16" y2="54" stroke="black" stroke-width="6" stroke-linecap="round" />'
    svg += '<line x1="26" y1="40" x2="30" y2="44" stroke="black" stroke-width="8" />'
    svg += '<path d="M29 32 A 8 8 0 0 1 41 28" stroke="black" stroke-width="2" fill="none" stroke-linecap="round" />'
    svg += '<text x="105" y="40" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="15" fill="black" text-anchor="middle">ALTO EM</text>'
    
    y_start = 63
    for i, nut in enumerate(active_nutrients):
        y_pos = y_start + (i * 55)
        svg += f'<rect x="15" y="{y_pos}" width="150" height="50" rx="12" ry="12" fill="black" />'
        
        if nut == "SÓDIO":
            svg += f'<text x="90" y="{y_pos + 31}" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="15" fill="white" text-anchor="middle">SÓDIO</text>'
        elif nut == "AÇÚCAR ADICIONADO":
            svg += f'<text x="90" y="{y_pos + 21}" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="12" fill="white" text-anchor="middle">AÇÚCAR</text>'
            svg += f'<text x="90" y="{y_pos + 38}" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="12" fill="white" text-anchor="middle">ADICIONADO</text>'
        elif nut == "GORDURA SATURADA":
            svg += f'<text x="90" y="{y_pos + 21}" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="12" fill="white" text-anchor="middle">GORDURA</text>'
            svg += f'<text x="90" y="{y_pos + 38}" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="12" fill="white" text-anchor="middle">SATURADA</text>'
            
    svg += '</svg>'
    return svg

def get_lupa_image_path(alto_acucar, alto_gordura, alto_sodio):
    db_path = os.path.join(BASE_DIR, "lupas_db.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                db = json.load(f)
            for key, val in db.items():
                if val.get("acucar") == alto_acucar and val.get("gordura") == alto_gordura and val.get("sodio") == alto_sodio:
                    filename = val.get("filename")
                    img_path = os.path.join(BASE_DIR, "lupas", filename)
                    if os.path.exists(img_path):
                        return img_path
        except Exception as e:
            logger.warning(f"Erro ao carregar banco de dados de lupas: {e}", exc_info=True)
    return None

def get_lupa_html(alto_acucar, alto_gordura, alto_sodio, width_px=180):
    img_path = get_lupa_image_path(alto_acucar, alto_gordura, alto_sodio)
    if img_path:
        try:
            import base64
            with open(img_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return f'<img src="data:image/png;base64,{encoded_string}" width="{width_px}" style="display: block; margin: 0 auto;" />'
        except Exception as e:
            logger.warning(f"Erro ao codificar imagem da lupa em base64: {e}", exc_info=True)
    return generate_anvisa_lupa_svg(alto_acucar, alto_gordura, alto_sodio)
