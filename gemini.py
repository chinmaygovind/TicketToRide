import cv2
import numpy as np
import os

# Load image
image_path = 'assets/board.jpg'
if not os.path.exists(image_path):
    print("File not found!")
    exit()

img = cv2.imread(image_path)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
overlay = img.copy()

# --- 1. ROBUST CITY DETECTION ---
# Widened range to catch the brown/orange dots even with JPEG artifacts
lower_city = np.array([0, 50, 50]) 
upper_city = np.array([30, 255, 255])
city_mask = cv2.inRange(hsv, lower_city, upper_city)

city_contours, _ = cv2.findContours(city_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

print("--- Verified Cities ---")
for cnt in city_contours:
    area = cv2.contourArea(cnt)
    if 50 < area < 800:
        # Check circularity to ignore text/numbers
        peri = cv2.arcLength(cnt, True)
        circularity = 4 * np.pi * (area / (peri * peri)) if peri > 0 else 0
        if circularity > 0.6:
            M = cv2.moments(cnt)
            if M["m00"] != 0:
                cx, cy = int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])
                print(f"City: ({cx}, {cy})")
                cv2.circle(overlay, (cx, cy), 12, (255, 0, 0), -1) # Solid blue

# --- 2. ROBUST RECTANGLE DETECTION ---
# Broadening the edge detection and using a simpler box drawing method
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
blurred = cv2.GaussianBlur(gray, (5, 5), 0)
# Lower thresholds to catch the faint grey routes
edges = cv2.Canny(blurred, 20, 80) 

rect_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

print("\n--- Verified Rectangles ---")
for cnt in rect_contours:
    area = cv2.contourArea(cnt)
    if 200 < area < 1500:
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        # Fix for the NumPy AttributeError
        box = np.array(box, dtype=np.int32) 
        
        # Filter by Aspect Ratio (Length vs Width)
        w, h = rect[1]
        if min(w, h) > 0:
            aspect_ratio = max(w, h) / min(w, h)
            if 1.8 < aspect_ratio < 4.5:
                # Ensure the box is inside the image frame
                if np.all(box >= 0):
                    print(f"Rectangle Corners: {box.tolist()}")
                    cv2.drawContours(overlay, [box], 0, (0, 255, 0), 2)

# Save the result so you can see it even if the popup fails
cv2.imwrite('validation_result.jpg', overlay)
cv2.imshow('Fixed Validation', overlay)
cv2.waitKey(0)
cv2.destroyAllWindows()