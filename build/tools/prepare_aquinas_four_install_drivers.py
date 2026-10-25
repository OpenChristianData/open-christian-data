"""Create exact one-work replay/install wrappers from retained supported examples."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    pairs=[('build/tools/install_murray_absolute_surrender_current.py','build/tools/install_aquinas_four_current.py'),('build/tools/replay_murray_absolute_surrender_current.py','build/tools/replay_aquinas_four_current.py'),('reports/_logs/murray-absolute-surrender-reconciliation-20261001-v1/prove_isolated_rollback.py','build/tools/prove_aquinas_four_rollback.py')]
    for original,output in pairs:
        source=(ROOT/original).read_text(encoding='utf-8').replace('murray_absolute_surrender_current','aquinas_four_current').replace('murray-absolute-surrender-reconciliation-20261001-v1','aquinas-four-current-reconciliation-20261002-v1').replace('murray-absolute-surrender','aquinas-summa-theologica-four-parts').replace('murray-surrender-rollback-20261001-v1','aquinas-four-rollback-20261002-v1').replace('Murray','Aquinas four-component witness').replace('receipt["rows"] != 11','receipt["rows"] != 4')
        source=source.replace('Complete retained titlepage plus nine addresses and integral scripture index, lightly edited electronic collection; one existing identity and unchanged source text/evidence.','Exactly four retained electronic components of the existing partial English Summa witness, complete own contextual matter and question/article text; only the source-backed prose category prerequisite. All existing IDs/titles/language/acquisition/member-set/credit remain unchanged.')
        source=source.replace('Fresh process supported deterministic header binding over fresh complete source replay','Fresh process supported deterministic header binding over byte-identical retained-body package replay')
        target=ROOT/output
        if target.exists():raise FileExistsError(target)
        target.write_text(source,encoding='utf-8')
    print('Created own install/replay/isolated rollback drivers')
if __name__=='__main__':main()
