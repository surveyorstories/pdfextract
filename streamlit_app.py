import streamlit as st
import os
import tempfile
import shutil
import sys
from zipfile import ZipFile
import fitz
from PIL import Image, ImageDraw

try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st_canvas = None

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from converter import PDF2DXFConverter
except ImportError:
    st.error("Could not import converter. Make sure 'src/converter.py' exists.")
    st.stop()

st.set_page_config(
    page_title="PDF to DXF Converter", 
    page_icon="📐",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)

# Hide Streamlit menu and footer
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

st.title("📐 PDF to DXF Converter")
st.markdown("""
Convert your PDF drawings to DXF format for CAD software.
""")

uploaded_files = st.file_uploader("Choose PDF file(s)", type="pdf", accept_multiple_files=True)

# Sidebar Options
st.sidebar.header("Extract Content")
include_geom = st.sidebar.checkbox("Geometry", True)
include_text = st.sidebar.checkbox("Text", True)

st.sidebar.header("Filter Geometries")
skip_curves = st.sidebar.checkbox("Skip Curved Geometries (Bezier/Splines)", False)
min_size = st.sidebar.number_input("Minimum Size (points)", 0.0, 99999.0, 0.0, 1.0)

st.sidebar.header("Page Range")
process_all = st.sidebar.checkbox("Process all pages", True)
if not process_all:
    col1, col2 = st.sidebar.columns(2)
    page_from = col1.number_input("From", 1, 99999, 1)
    page_to = col2.number_input("To", 1, 99999, 99999)
else:
    page_from = 1
    page_to = 99999

crop_rect = None

if uploaded_files:
    st.markdown("### Preview & Crop")
    preview_file_name = st.selectbox("Select file to preview", [f.name for f in uploaded_files])
    file_obj = next(f for f in uploaded_files if f.name == preview_file_name)
    
    try:
        doc = fitz.open(stream=file_obj.read(), filetype="pdf")
        total_pages = len(doc)
        preview_page_num = st.number_input("Page to preview", 1, total_pages, 1) - 1
        page = doc[preview_page_num]
        page_w, page_h = page.rect.width, page.rect.height
        
        enable_crop = st.checkbox("Enable Crop Region")
        if enable_crop:
            col1, col2 = st.columns(2)
            with col1:
                crop_left = st.slider("Left Margin", 0.0, float(page_w), 0.0)
                crop_right = st.slider("Right Margin", 0.0, float(page_w), float(page_w))
            with col2:
                crop_top = st.slider("Top Margin", 0.0, float(page_h), 0.0)
                crop_bottom = st.slider("Bottom Margin", 0.0, float(page_h), float(page_h))
                
            if crop_left < crop_right and crop_top < crop_bottom:
                crop_rect = (crop_left, crop_top, crop_right, crop_bottom)
            else:
                st.warning("Invalid crop region. Left must be < Right, Top must be < Bottom.")
                crop_rect = None
        
        # Render image
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        if crop_rect:
            draw = ImageDraw.Draw(img, "RGBA")
            scale = 2.0
            draw.rectangle(
                [crop_rect[0]*scale, crop_rect[1]*scale, crop_rect[2]*scale, crop_rect[3]*scale],
                outline=(255, 0, 0, 255), width=4, fill=(255, 0, 0, 40)
        if enable_crop and st_canvas is not None:
            st.info("Draw a rectangle on the image below to set the crop region. Only the last drawn rectangle will be used.")
            
            # Calculate scale to fit canvas comfortably in the UI
            display_scale = min(1.0, 700.0 / page_w)
            pix = page.get_pixmap(matrix=fitz.Matrix(display_scale, display_scale), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.3)",
                stroke_width=2,
                stroke_color="rgba(255, 0, 0, 1)",
                background_image=img,
                update_streamlit=True,
                height=img.height,
                width=img.width,
                drawing_mode="rect",
                key="crop_canvas",
            )
            
        st.image(img, use_container_width=True)
            if canvas_result.json_data is not None and len(canvas_result.json_data["objects"]) > 0:
                obj = canvas_result.json_data["objects"][-1]
                x = obj["left"]
                y = obj["top"]
                w = obj["width"] * obj["scaleX"]
                h = obj["height"] * obj["scaleY"]
                crop_rect = (x / display_scale, y / display_scale, (x + w) / display_scale, (y + h) / display_scale)
            else:
                crop_rect = None

        else:
            if enable_crop and st_canvas is None:
                st.warning("Please install `streamlit-drawable-canvas` (`pip install streamlit-drawable-canvas`) to enable mouse dragging. Falling back to sliders.")
                col1, col2 = st.columns(2)
                with col1:
                    crop_left = st.slider("Left Margin", 0.0, float(page_w), 0.0)
                    crop_right = st.slider("Right Margin", 0.0, float(page_w), float(page_w))
                with col2:
                    crop_top = st.slider("Top Margin", 0.0, float(page_h), 0.0)
                    crop_bottom = st.slider("Bottom Margin", 0.0, float(page_h), float(page_h))
                    
                if crop_left < crop_right and crop_top < crop_bottom:
                    crop_rect = (crop_left, crop_top, crop_right, crop_bottom)
                else:
                    st.warning("Invalid crop region. Left must be < Right, Top must be < Bottom.")
                    crop_rect = None

            # Render image statically (fallback or no crop)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            if crop_rect and enable_crop:
                draw = ImageDraw.Draw(img, "RGBA")
                scale = 2.0
                draw.rectangle(
                    [crop_rect[0]*scale, crop_rect[1]*scale, crop_rect[2]*scale, crop_rect[3]*scale],
                    outline=(255, 0, 0, 255), width=4, fill=(255, 0, 0, 40)
                )
                
            st.image(img, use_container_width=True)
            
        doc.close()
    except Exception as e:
        st.error(f"Could not render preview: {e}")
    finally:
        file_obj.seek(0)
        
    if not include_geom and not include_text:
        st.warning("Please select at least one content type to extract (Geometry or Text) in the sidebar.")
    
    elif st.button("Convert to DXF"):
        with st.spinner("Converting..."):
            with tempfile.TemporaryDirectory() as tmpdirname:
                progress_bar = st.progress(0)
                total_files = len(uploaded_files)
                
                for idx, f_obj in enumerate(uploaded_files):
                    input_path = os.path.join(tmpdirname, f_obj.name)
                    with open(input_path, "wb") as f:
                        f.write(f_obj.getbuffer())
                        
                    base_name = os.path.splitext(f_obj.name)[0]
                    output_path = os.path.join(tmpdirname, f"{base_name}.dxf")
                    
                    try:
                        doc = fitz.open(input_path)
                        total_pages_file = len(doc)
                        doc.close()
                        
                        p_from = max(1, page_from)
                        p_to = min(total_pages_file, page_to)
                        pages_list = list(range(p_from - 1, p_to))
                        
                        if pages_list:
                            converter = PDF2DXFConverter(input_path)
                            converter.convert(
                                output_path=output_path,
                                pages=pages_list,
                                crop_rect=crop_rect,
                                min_size=min_size,
                                skip_curves=skip_curves,
                                include_geom=include_geom,
                                include_text=include_text
                            )
                    except Exception as e:
                        st.error(f"Error converting {f_obj.name}: {e}")
                        
                    progress_bar.progress((idx + 1) / total_files)
                    
                # Check what was generated (handle multi-page)
                generated_files = [f for f in os.listdir(tmpdirname) if f.endswith(".dxf")]
                
                if not generated_files:
                    st.error("No DXF files were generated.")
                elif len(generated_files) == 1:
                    # Single file download
                    file_path = os.path.join(tmpdirname, generated_files[0])
                    with open(file_path, "rb") as f:
                        st.download_button(
                            label="Download DXF",
                            data=f,
                            file_name=generated_files[0],
                            mime="application/dxf"
                        )
                    st.success("Conversion successful!")
                else:
                    # Multiple files - Zip them
                    zip_filename = "converted_files.zip"
                    zip_path = os.path.join(tmpdirname, zip_filename)
                    with ZipFile(zip_path, 'w') as zipObj:
                        for file in generated_files:
                            zipObj.write(os.path.join(tmpdirname, file), file)
                    
                    with open(zip_path, "rb") as f:
                        st.download_button(
                            label="Download All (ZIP)",
                            data=f,
                            file_name=zip_filename,
                            mime="application/zip"
                        )
                    st.success(f"Conversion successful! Generated {len(generated_files)} files.")

st.markdown("---")
st.markdown("Powered by **PyMuPDF** and **ezdxf**.")
