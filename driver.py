import outlookmsgfile
import sys

eml = outlookmsgfile.load(sys.argv[1])
with open(sys.argv[2], "w") as f:
    f.write(str(eml))
