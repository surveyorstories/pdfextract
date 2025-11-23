import streamlit as st
import os
import tempfile
import shutil
import sys
from zipfile import ZipFile

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

uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

if uploaded_file is not None:
    st.info(f"File uploaded: {uploaded_file.name}")
    
    if st.button("Convert to DXF"):
        with st.spinner("Converting..."):
            # Create a temporary directory
            with tempfile.TemporaryDirectory() as tmpdirname:
                # Save uploaded file
                input_path = os.path.join(tmpdirname, uploaded_file.name)
                with open(input_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Define output path
                output_filename = os.path.splitext(uploaded_file.name)[0] + ".dxf"
                output_path = os.path.join(tmpdirname, output_filename)
                
                try:
                    # Run conversion
                    converter = PDF2DXFConverter(input_path)
                    converter.convert(output_path)
                    
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
                        
                except Exception as e:
                    st.error(f"An error occurred: {e}")

st.markdown("---")
st.markdown("Powered by **PyMuPDF** and **ezdxf**.")
