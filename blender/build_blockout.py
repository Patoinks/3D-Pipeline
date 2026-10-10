import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from chibi_lib import *

def main():
    args,spec=arguments()
    result=build_character(spec,low=True)
    save_blend(args.out/'blockout.blend')
    return {**result,'blend':str(args.out/'blockout.blend')}

if __name__=='__main__':
    entry(main)
