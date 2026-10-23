"""Clean up a scanned, hand-drawn blueprint PDF by removing speckles (dots).

Install:  pip install pymupdf opencv-python-headless numpy
Run:      python clean_blueprint.py [input.pdf] [output.pdf] [min_dot_area]
"""
import sys

import cv2
import numpy as np
import pymupdf  # PyMuPDF


def get_page_zoom(page, fallback_dpi=300):
  """Returns the (x, y) zoom that renders `page` 1:1 with its embedded scan.

  Each page of these permit sets is one full-page 1-bit scan (~200 DPI).
  Rendering at the scan's own resolution means no pixel is resampled, which
  matters because the thin lines are only 1-2 px wide. Pages that are not a
  single full-page image are rendered at `fallback_dpi` instead.
  """
  images = page.get_images(full=True)
  if len(images) == 1 and page.rotation == 0:
    xref, width, height = images[0][0], images[0][2], images[0][3]
    rects = page.get_image_rects(xref)
    if len(rects) == 1:
      rect = rects[0]
      if (rect.width >= 0.9 * page.rect.width
          and rect.height >= 0.9 * page.rect.height):
        return width / rect.width, height / rect.height
  return fallback_dpi / 72, fallback_dpi / 72


def clean_blueprint_pdf(input_pdf_path, output_pdf_path, min_dot_area=12):
  """Removes isolated specks from every page and saves a clean PDF.

  min_dot_area is the smallest blob that is kept, in pixels at 300 DPI. It is
  scaled to the resolution actually used, so 12 means the same physical size
  whatever the scan resolution.
  """
  print(f"Opening {input_pdf_path}...")
  doc = pymupdf.open(input_pdf_path)
  cleaned_doc = pymupdf.open()

  for page_num in range(len(doc)):
    page = doc.load_page(page_num)

    # Render page to a grayscale pixmap at the scan's native resolution
    zoom_x, zoom_y = get_page_zoom(page)
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(zoom_x, zoom_y),
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
    print(
        f"Processing page {page_num + 1} of {len(doc)} "
        f"({pix.w}x{pix.h} px, {zoom_x * 72:.0f} DPI)..."
    )

    # 1. Binarization using Otsu's thresholding to separate drawing from background
    _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 2. Invert so lines/text are white (255) and background is black (0) for blob analysis
    inverted = cv2.bitwise_not(thresh)

    # 3. Connected Component Analysis to isolate and remove tiny dots
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inverted, connectivity=8
    )

    # Keep components larger than the threshold (drops isolated tiny speckles).
    # Done as one lookup per pixel: testing `labels == i` once per component
    # is O(components x pixels), i.e. hours for the ~100,000 specks on a page.
    min_area = min_dot_area * (zoom_x * 72 / 300) ** 2
    keep = np.where(stats[:, cv2.CC_STAT_AREA] >= min_area, 255, 0).astype(np.uint8)
    keep[0] = 0  # label 0 is the background
    cleaned_inverted = keep[labels]
    kept = int((keep[1:] > 0).sum())
    print(f"  removed {num_labels - 1 - kept:,} dots, kept {kept:,} lines/marks")

    # Invert back to dark lines on a clean white background
    cleaned_img = cv2.bitwise_not(cleaned_inverted)

    # Add it to the new PDF losslessly (no JPEG), on a page of the original
    # size so the drawing scale is unchanged
    cleaned_pix = pymupdf.Pixmap(
        pymupdf.csGRAY, pix.w, pix.h, cleaned_img.tobytes(), False
    )
    cleaned_page = cleaned_doc.new_page(
        width=page.rect.width, height=page.rect.height
    )
    cleaned_page.insert_image(
        cleaned_page.rect, pixmap=cleaned_pix, keep_proportion=False
    )

  # Save all processed pages back into a single clean PDF
  if len(cleaned_doc):
    cleaned_doc.save(output_pdf_path, garbage=4, deflate=True)
  print(f"Success! Cleaned PDF saved to: {output_pdf_path}")


if __name__ == "__main__":
  input_file = (
      sys.argv[1] if len(sys.argv) > 1
      else "99-AS07 2117 BONNIE BRAE APPPROVED PLANS.pdf"
  )
  output_file = sys.argv[2] if len(sys.argv) > 2 else "cleaned_blueprint.pdf"
  # Adjust min_dot_area if needed:
  # Increase if speckles remain, decrease if small text/periods are affected.
  min_dot_area = int(sys.argv[3]) if len(sys.argv) > 3 else 12
  clean_blueprint_pdf(input_file, output_file, min_dot_area=min_dot_area)
