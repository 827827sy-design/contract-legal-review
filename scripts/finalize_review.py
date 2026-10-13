"""First-review completeness gate. WorkBuddy generates/repairs; no hidden LLM."""
import argparse,subprocess,sys,json
from pathlib import Path
from common import read_json
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--task-dir',required=True);ap.add_argument('--allow-incomplete',action='store_true');a=ap.parse_args();root=Path(__file__).parent
    subprocess.run([sys.executable,'-B','-X','utf8',str(root/'validate_review.py'),'--task-dir',a.task_dir,'--index-dir',str(root.parent/'law_index')],check=True)
    coverage=read_json(Path(a.task_dir)/'review_result.json')['review_meta']['suggestion_coverage']
    print(json.dumps(coverage,ensure_ascii=False))
    if coverage['incomplete_count'] and not a.allow_incomplete:
        print('首次审查仍有生成、关联或模型核验未完成。请WorkBuddy按generation_requests.json及quality_requests.json补全或修复；不能把系统未完成步骤转嫁给用户。');sys.exit(2)
    subprocess.run([sys.executable,'-B','-X','utf8',str(root/'render_report.py'),'--task-dir',a.task_dir],check=True)
if __name__=='__main__':main()
