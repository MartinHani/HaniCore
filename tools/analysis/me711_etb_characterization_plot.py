"""Plot a saved characterization log without accessing or changing the ECU."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
from me711_etb_characterization_analyze import read_log

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=read_log(a.log)
    fig,axes=plt.subplots(3,1,figsize=(14,9),sharex=True)
    t=[r['time'] for r in rows]
    for channel,label in [('sweepRequested','Requested target'),('dbwTargetX10','Effective target'),('dbwActualX10','Actual')]:
        axes[0].plot(t,[r.get(channel,0) for r in rows],label=label,linewidth=1.2)
    axes[0].set_ylabel('Travel (%)');axes[0].set_ylim(-5,110)
    axes[1].plot(t,[r['sweepSignedDuty'] for r in rows],label='Signed motor duty')
    axes[1].set_ylabel('Duty (%)');axes[1].set_ylim(-85,85)
    for channel,label,scale in [('dbwTermP','P',1),('dbwInteg','I',.1),('dbwTermD','D',1),('dbwTermFf','Bias/FF',1)]:
        axes[2].plot(t,[r.get(channel,0)*scale for r in rows],label=label,linewidth=1)
    axes[2].set_ylabel('Contribution (%)');axes[2].set_xlabel('Elapsed time (s)')
    slam=next((r['time'] for r in rows if r.get('sweepSegment',0)>=33),None)
    for ax in axes:
        ax.grid(alpha=.25);ax.legend(loc='upper right',ncol=4)
        if slam is not None:ax.axvspan(slam,t[-1],color='orange',alpha=.08)
    axes[0].set_title('Physical ETB characterization — shaded region: production APP-demand slams\n'
                      'Serial samples; fast transient detail is limited by capture resolution')
    fig.tight_layout();a.out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.out,dpi=160);plt.close(fig)

if __name__=='__main__':main()
