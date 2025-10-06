"""
PDF Chapter Detection and Splitting Module
Supports nested bookmark structures (Parts → Chapters)
Handles multi-level hierarchies with readable filenames
"""

import pikepdf
import fitz  # PyMuPDF
import pdfplumber
from collections import defaultdict
import re
import os

class PDFChapterSplitter:
    """
    Intelligently detects and splits PDF chapters
    Handles nested bookmark structures (e.g., Parts containing Chapters)
    Creates readable filenames using actual chapter titles
    """
    
    def __init__(self, pdf_path):
        """Initialize with PDF file path"""
        self.pdf_path = pdf_path
        self.detection_method = None
        
    def detect_chapters(self):
        """
        Main chapter detection method
        Tries bookmarks first (including nested), then heading detection
        
        Returns:
            List of chapter dictionaries with title and page numbers
        """
        # Try bookmark-based detection first (with nesting support)
        chapters = self._detect_from_bookmarks()
        
        if chapters:
            self.detection_method = 'bookmarks'
            return chapters
        
        # Fallback to heading-based detection
        chapters = self._detect_from_headings()
        self.detection_method = 'headings'
        
        return chapters
    
    def _detect_from_bookmarks(self):
        """
        Extract chapters from PDF bookmarks/outline
        RECURSIVELY processes nested bookmarks (Parts → Chapters → Subchapters)
        Returns ALL leaf-level chapters, not just top-level items
        """
        try:
            pdf = pikepdf.Pdf.open(self.pdf_path)
            
            # Check if PDF has outline/bookmarks
            if not hasattr(pdf, 'open_outline'):
                return []
            
            all_chapters = []
            
            with pdf.open_outline() as outline:
                if not outline.root:
                    return []
                
                # Recursively extract ALL nested bookmarks
                chapter_num = 1
                all_chapters = self._extract_nested_bookmarks(
                    outline.root, 
                    pdf, 
                    chapter_num,
                    parent_title=""
                )
            
            # Calculate end pages for each chapter
            all_chapters = self._calculate_end_pages(all_chapters, len(pdf.pages))
            pdf.close()
            
            return all_chapters
        
        except Exception as e:
            print(f"Bookmark detection failed: {e}")
            return []
    
    def _extract_nested_bookmarks(self, items, pdf, start_num=1, parent_title="", level=0):
        """
        RECURSIVELY extract bookmarks at ALL nesting levels
        
        Args:
            items: List of outline items to process
            pdf: pikepdf Pdf object
            start_num: Starting chapter number
            parent_title: Title of parent item (e.g., "Part I")
            level: Current nesting level (0 = root)
        
        Returns:
            List of all leaf-level bookmarks (actual chapters)
        """
        chapters = []
        chapter_num = start_num
        
        for item in items:
            try:
                # Get page number for this bookmark
                page_num = self._get_bookmark_page(item, pdf)
                title = str(item.title)
                
                # Check if this item has children (nested bookmarks)
                has_children = hasattr(item, 'children') and len(item.children) > 0
                
                if has_children:
                    # This is a PARENT (e.g., "Part I", "Section A")
                    # Recursively process children
                    print(f"{'  ' * level}📁 Parent: {title} (has {len(item.children)} children)")
                    
                    # Build parent context for better chapter titles
                    full_parent = f"{parent_title} → {title}" if parent_title else title
                    
                    # RECURSIVELY extract nested chapters
                    nested_chapters = self._extract_nested_bookmarks(
                        item.children,
                        pdf,
                        chapter_num,
                        parent_title=full_parent,
                        level=level + 1
                    )
                    
                    chapters.extend(nested_chapters)
                    chapter_num += len(nested_chapters)
                    
                else:
                    # This is a LEAF chapter (actual content chapter)
                    if page_num is not None:
                        # Build full chapter title with parent context
                        full_title = f"{parent_title} → {title}" if parent_title else title
                        
                        print(f"{'  ' * level}📄 Chapter {chapter_num}: {full_title} (page {page_num})")
                        
                        chapters.append({
                            'title': title,  # Original title only
                            'full_title': full_title,  # Full path with parents
                            'parent': parent_title,
                            'start_page': page_num,
                            'chapter_num': chapter_num,
                            'level': level
                        })
                        chapter_num += 1
            
            except Exception as e:
                print(f"Warning: Could not process bookmark: {e}")
                continue
        
        return chapters
    
    def _get_bookmark_page(self, outline_item, pdf):
        """
        Extract page number from bookmark outline item
        Handles direct and indirect destinations
        """
        try:
            if hasattr(outline_item, 'destination'):
                dest = outline_item.destination
                if dest and len(dest) > 0:
                    page_obj = dest[0]
                    return pikepdf.Page(page_obj).index
            
            # Try action dictionary as fallback
            if hasattr(outline_item, 'action'):
                action = outline_item.action
                if action and '/D' in action:
                    dest = action['/D']
                    if dest and len(dest) > 0:
                        page_obj = dest[0]
                        return pikepdf.Page(page_obj).index
        
        except Exception as e:
            print(f"Could not extract page from bookmark: {e}")
        
        return None
    
    def _detect_from_headings(self):
        """
        Detect chapters based on heading analysis
        Uses font size, text patterns, and layout structure
        """
        try:
            doc = fitz.open(self.pdf_path)
            
            # Analyze font sizes across document
            font_sizes = self._analyze_font_sizes(doc)
            
            # Get threshold for heading font size (top 10% largest)
            heading_threshold = self._calculate_heading_threshold(font_sizes)
            
            chapters = []
            chapter_num = 1
            
            # Scan pages for potential chapter headings
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Extract text with font information
                blocks = page.get_text("dict")["blocks"]
                
                for block in blocks:
                    if "lines" not in block:
                        continue
                    
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            font_size = span["size"]
                            
                            # Check if this looks like a chapter heading
                            if (font_size >= heading_threshold and 
                                self._is_chapter_heading(text)):
                                
                                chapters.append({
                                    'title': text,
                                    'full_title': text,
                                    'parent': '',
                                    'start_page': page_num,
                                    'chapter_num': chapter_num,
                                    'font_size': font_size,
                                    'level': 0
                                })
                                chapter_num += 1
            
            # Calculate end pages
            chapters = self._calculate_end_pages(chapters, len(doc))
            doc.close()
            
            return chapters
        
        except Exception as e:
            print(f"Heading detection failed: {e}")
            return self._create_default_chapters()
    
    def _analyze_font_sizes(self, doc):
        """Extract all font sizes from document for analysis"""
        font_sizes = []
        
        for page_num in range(min(20, len(doc))):  # Sample first 20 pages
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            font_sizes.append(span["size"])
        
        return font_sizes
    
    def _calculate_heading_threshold(self, font_sizes):
        """Calculate font size threshold for headings (90th percentile)"""
        if not font_sizes:
            return 14.0
        
        sorted_sizes = sorted(font_sizes, reverse=True)
        percentile_90_idx = int(len(sorted_sizes) * 0.1)
        
        return sorted_sizes[percentile_90_idx] if percentile_90_idx < len(sorted_sizes) else 14.0
    
    def _is_chapter_heading(self, text):
        """
        Check if text matches chapter heading patterns
        Looks for common chapter indicators
        """
        # Patterns that typically indicate chapter headings
        patterns = [
            r'^chapter\s+\d+',  # "Chapter 1", "Chapter 2", etc.
            r'^\d+\.\s+[A-Z]',  # "1. Introduction", "2. Methods"
            r'^[A-Z][A-Z\s]{5,}$',  # ALL CAPS HEADINGS
            r'^Part\s+[IVX\d]+',  # "Part I", "Part II"
            r'^Section\s+\d+',  # "Section 1"
        ]
        
        text_lower = text.lower()
        
        # Check patterns
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return True
        
        # Additional heuristics: short text, starts with capital
        if (len(text) < 100 and 
            len(text) > 3 and 
            text[0].isupper()):
            return True
        
        return False
    
    def _calculate_end_pages(self, chapters, total_pages):
        """Calculate end page for each chapter"""
        for i in range(len(chapters)):
            if i < len(chapters) - 1:
                chapters[i]['end_page'] = chapters[i + 1]['start_page'] - 1
            else:
                chapters[i]['end_page'] = total_pages - 1
        
        return chapters
    
    def _create_default_chapters(self):
        """Create default chapter structure if detection fails"""
        pdf = pikepdf.Pdf.open(self.pdf_path)
        total_pages = len(pdf.pages)
        pdf.close()
        
        # Split into equal chunks of ~20 pages
        chapters = []
        pages_per_chapter = 20
        
        for i in range(0, total_pages, pages_per_chapter):
            chapter_num = len(chapters) + 1
            chapters.append({
                'title': f'Section {chapter_num}',
                'full_title': f'Section {chapter_num}',
                'parent': '',
                'start_page': i,
                'end_page': min(i + pages_per_chapter - 1, total_pages - 1),
                'chapter_num': chapter_num,
                'level': 0
            })
        
        return chapters
    
    def split_chapters(self, chapters, output_dir):
        """
        Split PDF into separate files based on detected chapters
        Preserves original formatting
        Creates READABLE filenames using actual chapter titles
        
        Args:
            chapters: List of chapter dictionaries
            output_dir: Directory to save split PDFs
        
        Returns:
            List of output file paths
        """
        output_files = []
        
        try:
            pdf = pikepdf.Pdf.open(self.pdf_path)
            
            for chapter in chapters:
                # Create new PDF for this chapter
                chapter_pdf = pikepdf.Pdf.new()
                
                # Extract pages for this chapter
                start = chapter['start_page']
                end = chapter['end_page']
                
                for page_num in range(start, end + 1):
                    if page_num < len(pdf.pages):
                        chapter_pdf.pages.append(pdf.pages[page_num])
                
                # Generate READABLE filename using ACTUAL chapter title
                display_title = chapter.get('full_title', chapter['title'])
                chapter_title = chapter['title']
                
                # Clean title for filename (remove special characters)
                # Remove invalid filename characters for Windows/Mac/Linux
                safe_title = re.sub(r'[<>:"/\\|?*]', '', chapter_title)  # Remove invalid chars
                safe_title = re.sub(r'\s+', ' ', safe_title).strip()  # Clean whitespace
                safe_title = safe_title[:80]  # Limit length to 80 characters
                
                # Remove leading/trailing dots and spaces (Windows issue)
                safe_title = safe_title.strip('. ')
                
                # If title is empty after cleaning, use generic name
                if not safe_title:
                    safe_title = f"Chapter_{chapter['chapter_num']}"
                
                # Filename format: "01 - Chapter Title.pdf" (readable and sortable)
                filename = f"{chapter['chapter_num']:02d} - {safe_title}.pdf"
                output_path = os.path.join(output_dir, filename)
                
                # Save chapter PDF
                chapter_pdf.save(output_path)
                
                output_files.append({
                    'filename': filename,
                    'title': chapter['title'],
                    'full_title': display_title,
                    'parent': chapter.get('parent', ''),
                    'pages': f"{start + 1}-{end + 1}",
                    'path': os.path.relpath(output_path, 'output')
                })
            
            pdf.close()
            
        except Exception as e:
            raise Exception(f"Failed to split PDF: {str(e)}")
        
        return output_files
