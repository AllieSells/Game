
import time

var = 3

t0 = time.monotonic()
# ELIF chain
for x in range(100000000):
    if var == 1:
        r = 307509571^370459275
    elif var == 2:
        r = 307509571^370459275
    elif var == 3:
        r = 307509571^370459275
t1 = time.monotonic()
print(f"If-elif chain took {t1 - t0:.100f} seconds")
# Switch
t0 = time.monotonic()
for x in range(100000000):
    match var:
        case 1:
            r = 307509571^370459275
        case 2:
            r = 307509571^370459275
        case 3:
            r = 307509571^370459275
t1 = time.monotonic()
print(f"Match-case took {t1 - t0:.100f} seconds")
