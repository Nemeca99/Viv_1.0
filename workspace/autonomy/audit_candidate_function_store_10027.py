import sqlite3
p=r'L:\LocalCoder\workspace\autonomy\learning\neural_runs\candidate_verified_functions.sqlite3'
db=sqlite3.connect('file:'+p.replace('\\','/')+'?mode=ro',uri=True)
print('quick_check',db.execute('pragma quick_check').fetchone()[0])
for t in ('functions','function_versions','proposal_attempts'):
 print('schema',t,db.execute("select sql from sqlite_master where type='table' and name=?",(t,)).fetchone()[0])
for row in db.execute('select f.language,f.domain,count(*) from function_versions v join functions f using(function_key) where v.gate_status=\'ALLOW\' group by f.language,f.domain order by f.language,f.domain'):
 print('accepted',row)
print('active_names',db.execute('select f.language,f.domain,f.function_name,count(*) from active_versions a join functions f using(function_key) group by f.language,f.domain,f.function_name').fetchall())