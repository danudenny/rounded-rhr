import streamlit as st
import geopandas as gpd
import pandas as pd
import re
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform
from shapely.geometry.polygon import orient
from shapely import is_ccw
from shapely import wkt
import io
import tempfile
import os

# Set page config
st.set_page_config(
    page_title="GeoJSON Precision Fixer",
    page_icon="🗺️",
    layout="wide"
)

# Helper Functions
def round_coordinates(geom, precision=6):
    if geom is None:
        return None

    def round_coords(x, y, z=None):
        # Round and format to exact precision (no more, no less)
        x_rounded = float(f"{x:.{precision}f}")
        y_rounded = float(f"{y:.{precision}f}")
        
        if z is not None:
            z_rounded = float(f"{z:.{precision}f}")
            return (x_rounded, y_rounded, z_rounded)
        return (x_rounded, y_rounded)

    return transform(round_coords, geom)


def fix_cw_to_ccw(geom):
    """Fix counterclockwise orientation for polygons and multipolygons."""
    try:
        if geom is None or geom.is_empty:
            return geom
            
        if isinstance(geom, Polygon):
            return orient(geom, sign=1.0)
        elif isinstance(geom, MultiPolygon):
            fixed_polygons = [orient(poly, sign=1.0) for poly in geom.geoms]
            return MultiPolygon(fixed_polygons)
        else:
            return geom
    except Exception as e:
        st.error(f"Error fixing counterclockwise orientation: {e}")
        return geom


def check_coordinate_precision(geometry, max_decimals=6):
    if geometry is None:
        return False
    
    wkt_string = str(geometry)
    coords = re.findall(r"(-?\d+\.\d+)", wkt_string)
    return any(len(coord.split(".")[1]) > max_decimals for coord in coords)


def check_orientation_stats(gdf):
    """Check and report orientation statistics."""
    cw_count = 0
    ccw_count = 0
    other_count = 0
    
    for geom in gdf["geometry"]:
        if isinstance(geom, Polygon):
            if is_ccw(geom.exterior):
                ccw_count += 1
            else:
                cw_count += 1
        elif isinstance(geom, MultiPolygon):
            largest_poly = max(geom.geoms, key=lambda p: p.area)
            if is_ccw(largest_poly.exterior):
                ccw_count += 1
            else:
                cw_count += 1
        else:
            other_count += 1
    
    return {"ccw": ccw_count, "cw": cw_count, "other": other_count}


def load_file(uploaded_file, file_type, **kwargs):
    """Load file based on type with appropriate parameters."""
    try:
        if file_type == "GeoJSON":
            with tempfile.NamedTemporaryFile(delete=False, suffix='.geojson') as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            gdf = gpd.read_file(tmp_path)
            os.unlink(tmp_path)
            return gdf
            
        elif file_type == "CSV":
            # Read CSV with specified options
            df = pd.read_csv(
                uploaded_file,
                sep=kwargs.get('separator', ','),
                encoding=kwargs.get('encoding', 'utf-8')
            )
            
            # Convert geometry column from WKT to geometry objects
            geom_column = kwargs.get('geometry_column')
            if geom_column and geom_column in df.columns:
                df['geometry'] = df[geom_column].apply(
                    lambda x: wkt.loads(x) if pd.notna(x) else None
                )
                gdf = gpd.GeoDataFrame(df, geometry='geometry')
                
                # Set CRS if provided
                if kwargs.get('crs'):
                    gdf.set_crs(kwargs['crs'], inplace=True)
                
                return gdf
            else:
                st.error(f"Geometry column '{geom_column}' not found in CSV")
                return None
                
        elif file_type == "Shapefile":
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            gdf = gpd.read_file(f"zip://{tmp_path}")
            os.unlink(tmp_path)
            return gdf
            
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None


# Streamlit App
st.title("🗺️ Geospatial Coordinate Precision Fixer")
st.markdown("Fix coordinate precision and polygon orientation in your geospatial data")

# Sidebar for configuration
st.sidebar.header("⚙️ Configuration")

# File upload
uploaded_file = st.sidebar.file_uploader(
    "Upload your file",
    type=["geojson", "csv", "zip"],
    help="Supports GeoJSON, CSV (with WKT geometry), and Shapefile (as ZIP)"
)

if uploaded_file:
    # Detect file type
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    if file_extension == 'geojson':
        file_type = "GeoJSON"
    elif file_extension == 'csv':
        file_type = "CSV"
    elif file_extension == 'zip':
        file_type = "Shapefile"
    else:
        st.error("Unsupported file format")
        st.stop()
    
    st.sidebar.info(f"📄 File type detected: **{file_type}**")
    
    # CSV-specific options
    csv_options = {}
    if file_type == "CSV":
        st.sidebar.subheader("CSV Options")
        
        # Separator
        separator = st.sidebar.selectbox(
            "Separator",
            [',', ';', '|', '\t'],
            index=0,
            help="Choose the column separator"
        )
        csv_options['separator'] = separator
        
        # Encoding
        encoding = st.sidebar.selectbox(
            "Encoding",
            ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252'],
            index=0
        )
        csv_options['encoding'] = encoding
        
        # Preview CSV to select geometry column
        try:
            preview_df = pd.read_csv(uploaded_file, sep=separator, encoding=encoding, nrows=5)
            uploaded_file.seek(0)  # Reset file pointer
            
            geometry_column = st.sidebar.selectbox(
                "Geometry Column",
                options=preview_df.columns.tolist(),
                help="Select the column containing WKT geometry"
            )
            csv_options['geometry_column'] = geometry_column
            
            # CRS input
            crs_input = st.sidebar.text_input(
                "CRS (optional)",
                value="EPSG:4326",
                help="Coordinate Reference System (e.g., EPSG:4326)"
            )
            if crs_input:
                csv_options['crs'] = crs_input
                
        except Exception as e:
            st.error(f"Error previewing CSV: {e}")
            st.stop()
    
    # Processing options
    st.sidebar.subheader("Processing Options")
    
    precision = st.sidebar.slider(
        "Decimal Precision",
        min_value=1,
        max_value=15,
        value=6,
        help="Number of decimal places for coordinates"
    )
    
    fix_orientation = st.sidebar.checkbox(
        "Fix Polygon Orientation",
        value=True,
        help="Ensure polygons are counterclockwise (CCW)"
    )
    
    # Output format
    output_format = st.sidebar.selectbox(
        "Output Format",
        ["GeoJSON", "Shapefile", "GeoPackage"],
        index=0
    )
    
    # Process button
    if st.sidebar.button("🚀 Process File", type="primary"):
        with st.spinner("Loading file..."):
            gdf = load_file(uploaded_file, file_type, **csv_options)
        
        if gdf is not None:
            # Display original data info
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Features", len(gdf))
            
            with col2:
                geom_types = gdf.geometry.geom_type.value_counts()
                st.metric("Geometry Types", len(geom_types))
            
            with col3:
                if gdf.crs:
                    st.metric("CRS", str(gdf.crs))
                else:
                    st.metric("CRS", "Not Set")
            
            # Show geometry type distribution
            st.subheader("📊 Geometry Type Distribution")
            geom_df = pd.DataFrame({
                'Type': geom_types.index,
                'Count': geom_types.values
            })
            st.dataframe(geom_df, use_container_width=True)
            
            # Check original precision
            st.subheader("🔍 Original Data Analysis")
            
            high_precision_count = gdf['geometry'].apply(
                lambda g: check_coordinate_precision(g, precision)
            ).sum()
            
            st.info(f"**Features with >{precision} decimal places:** {high_precision_count}")
            
            # Check orientation
            if fix_orientation:
                orig_orientation = check_orientation_stats(gdf)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Counterclockwise", orig_orientation['ccw'])
                with col2:
                    st.metric("Clockwise", orig_orientation['cw'])
                with col3:
                    st.metric("Other Types", orig_orientation['other'])
            
            # Process the data
            st.subheader("⚙️ Processing...")
            progress_bar = st.progress(0)
            
            # Round coordinates
            progress_bar.progress(33)
            gdf['geometry'] = gdf['geometry'].apply(
                lambda geom: round_coordinates(geom, precision)
            )
            
            # Fix orientation
            if fix_orientation:
                progress_bar.progress(66)
                gdf['geometry'] = gdf['geometry'].apply(fix_cw_to_ccw)
            
            progress_bar.progress(100)
            st.success("✅ Processing complete!")
            
            # Show results
            st.subheader("📈 Results")
            
            # Verify precision
            new_high_precision = gdf['geometry'].apply(
                lambda g: check_coordinate_precision(g, precision)
            ).sum()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "High Precision Before",
                    high_precision_count,
                    delta=None
                )
            with col2:
                st.metric(
                    "High Precision After",
                    new_high_precision,
                    delta=-(high_precision_count - new_high_precision),
                    delta_color="inverse"
                )
            
            # Show orientation after
            if fix_orientation:
                new_orientation = check_orientation_stats(gdf)
                st.write("**Orientation After Processing:**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        "Counterclockwise",
                        new_orientation['ccw'],
                        delta=new_orientation['ccw'] - orig_orientation['ccw']
                    )
                with col2:
                    st.metric(
                        "Clockwise",
                        new_orientation['cw'],
                        delta=-(orig_orientation['cw'] - new_orientation['cw']),
                        delta_color="inverse"
                    )
                with col3:
                    st.metric("Other Types", new_orientation['other'])
            
            # Preview processed data
            st.subheader("👁️ Data Preview")
            preview_df = pd.DataFrame(gdf.drop(columns='geometry'))
            st.dataframe(preview_df.head(10), use_container_width=True)
            
            # Download processed file
            st.subheader("💾 Download Processed File")
            
            # Create output file
            output_buffer = io.BytesIO()
            
            if output_format == "GeoJSON":
                gdf.to_file(output_buffer, driver="GeoJSON")
                mime_type = "application/json"
                file_extension = "geojson"
            elif output_format == "Shapefile":
                with tempfile.TemporaryDirectory() as tmpdir:
                    output_path = os.path.join(tmpdir, "output.shp")
                    gdf.to_file(output_path)
                    
                    # Create zip file
                    import zipfile
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                            file_path = output_path.replace('.shp', ext)
                            if os.path.exists(file_path):
                                zipf.write(file_path, os.path.basename(file_path))
                    output_buffer = zip_buffer
                mime_type = "application/zip"
                file_extension = "zip"
            else:  # GeoPackage
                gdf.to_file(output_buffer, driver="GPKG")
                mime_type = "application/geopackage+sqlite3"
                file_extension = "gpkg"
            
            output_buffer.seek(0)
            
            # Generate output filename
            original_name = uploaded_file.name.rsplit('.', 1)[0]
            output_filename = f"{original_name}_fixed_{precision}dp"
            if fix_orientation:
                output_filename += "_ccw"
            output_filename += f".{file_extension}"
            
            st.download_button(
                label=f"📥 Download {output_format}",
                data=output_buffer,
                file_name=output_filename,
                mime=mime_type,
                type="primary"
            )

else:
    # Welcome screen
    st.info("👈 Upload a file to get started")
    
    st.markdown("""
    ### Features:
    - ✅ Support for multiple formats (GeoJSON, CSV with WKT, Shapefile)
    - ✅ Adjustable coordinate precision (1-15 decimal places)
    - ✅ Fix polygon orientation (Clockwise → Counterclockwise)
    - ✅ Customizable CSV options (separator, encoding, geometry column)
    - ✅ Export to GeoJSON, Shapefile, or GeoPackage
    - ✅ Detailed statistics and preview
    
    ### How to use:
    1. Upload your geospatial file in the sidebar
    2. Configure processing options
    3. Click "Process File"
    4. Download the corrected file
    
    ### Supported Input Formats:
    - **GeoJSON** (.geojson)
    - **CSV** (.csv) with WKT geometry column
    - **Shapefile** (.zip) containing .shp, .shx, .dbf files
    """)
    
    # Example section
    with st.expander("📖 CSV Format Example"):
        st.markdown("""
        Your CSV should contain a column with WKT (Well-Known Text) geometry:
        
        ```
        id,name,geometry
        1,Feature1,"POLYGON((106.8 -6.2, 106.9 -6.2, 106.9 -6.1, 106.8 -6.1, 106.8 -6.2))"
        2,Feature2,"POINT(106.85 -6.15)"
        ```
        """)
