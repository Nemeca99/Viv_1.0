import json
p='runs/20261008T074336971050Z/training_log.jsonl'
rows=[]
for line in open(p):
 x=json.loads(line)['values']
 if x[22]=='ACTION' and int(x[1])>=104700: rows.append(x)
for x in rows[:100]: print(x[1],x[2],x[3],x[5],x[7],x[8],x[10],x[11])
print('n',len(rows))
