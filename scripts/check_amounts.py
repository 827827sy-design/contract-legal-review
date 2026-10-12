"""Arithmetic checks only; no inferred tax rates or legal/tax advice."""
from __future__ import annotations
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from common import read_json,write_json,force_utf8_stdio

DIGITS=dict(zip('零壹贰叁肆伍陆柒捌玖',range(10)))
def financial_number(text):
    text=text.replace('人民币','').replace('圆','元').strip()
    integer,_,fraction=text.partition('元');total=section=num=0
    for ch in integer:
        if ch in DIGITS:num=DIGITS[ch]
        elif ch in {'拾','佰','仟'}:
            section+=(num or 1)*{'拾':10,'佰':100,'仟':1000}[ch];num=0
        elif ch in {'万','亿'}:
            section+=num;num=0
            if ch=='万':section*=10000
            else:total=(total+section)*100000000;section=0
        else:raise ValueError('不支持的大写金额格式。')
    result=Decimal(total+section+num);digit=0
    for ch in fraction:
        if ch in DIGITS:digit=DIGITS[ch]
        elif ch in {'角','分'}:result+=Decimal(digit)/({'角':10,'分':100}[ch]);digit=0
        elif ch not in {'整','正'}:raise ValueError('不支持的大写金额小数。')
    return result

def check(record):
    findings=[]
    if record.get('numeric') is not None and record.get('uppercase'):
        if Decimal(str(record['numeric']).replace(',',''))!=financial_number(record['uppercase']):findings.append('数字金额与中文大写不一致')
    # Explicit opt-in only for price: deposits and penalties are not mechanically taxed.
    if record.get('nature')=='price':
        names=['net','rate','tax','gross'];missing=[k for k in names if record.get(k) in (None,'')]
        if missing:findings.append('价税字段待补充：'+','.join(missing))
        else:
            net,rate,tax,gross=(Decimal(str(record[k])) for k in names)
            if abs((net*rate).quantize(Decimal('.01'))-tax)>Decimal('.01'):findings.append('税额计算不一致')
            if abs(net+tax-gross)>Decimal('.01'):findings.append('含税总价不等于不含税金额加税额')
    return findings

def main():
    force_utf8_stdio();ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args();records=read_json(Path(args.input));results=[]
    for record in records:
        try:findings=check(record)
        except (ValueError,InvalidOperation) as error:findings=['金额无法机械解析，需人工核实：'+str(error)]
        results.append({'node_id':record.get('node_id'),'findings':findings})
    write_json(Path(args.out),results);print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
