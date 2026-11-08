import os
from pathlib import Path
import tempfile
import time
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import create_app


class AppTests(unittest.TestCase):
    @patch('model_client.time.sleep')
    @patch('model_client._request')
    def test_resume_after_restart_reuses_persisted_remote_job(self,remote,sleep):
        remote.side_effect=[{'id':'job_persisted','status':'queued'},
                            {'id':'job_persisted','status':'done','result':{'text':'{"ok":true}','finishReason':'STOP'}}]
        calls=[]
        def analyze(*args,**kwargs):
            calls.append(1)
            data,meta=kwargs['client']('fixture',{'type':'object'},provider='router',model='fixture',timeout=1 if len(calls)==1 else 60)
            return {'blocks':[],'risks':[],'remote_job':meta['job_id']}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ROUTER_API_KEY':'synthetic'}),patch('app.analyze_document',side_effect=analyze):
            path=Path(directory)/'persisted.db'
            with TestClient(create_app(path),base_url='http://localhost') as first:
                started=first.post('/api/analyses',json={'text':'Документ для проверки восстановления запроса'}).json()
                url='/api/analyses/'+started['id']
                for _ in range(100):
                    state=first.get(url).json()
                    if state['status']=='failed':break
                    time.sleep(.01)
                self.assertEqual(state['status'],'failed')
                cookies=first.cookies
            with TestClient(create_app(path),base_url='http://localhost',cookies=cookies) as second:
                self.assertEqual(second.post(url+'/resume').status_code,202)
                for _ in range(100):
                    state=second.get(url).json()
                    if state['status']=='done':break
                    time.sleep(.01)
                self.assertEqual(state['status'],'done')
                self.assertEqual(state['result']['remote_job'],'job_persisted')
                self.assertEqual(remote.call_count,2)

    def test_results_belong_to_session_and_restore_immutable_input(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'ROUTER_API_KEY':'synthetic'}), patch('app.analyze_document',return_value={'blocks':[],'risks':[]}):
            path=Path(directory)/'private.db'
            app=create_app(path)
            with TestClient(app,base_url='http://localhost') as owner:
                payload={'text':'Документ A: исходные условия для анализа','doc_type':'terms','model':'gemini-3.1-flash-lite','provider':'router'}
                started=owner.post('/api/analyses',json=payload)
                url='/api/analyses/'+started.json()['id']
                for _ in range(100):
                    result=owner.get(url)
                    if result.json()['status']=='done':break
                    time.sleep(.01)
                outsider=TestClient(app,base_url='http://localhost')
                self.assertEqual(outsider.get(url).status_code,404)
                self.assertEqual(result.json()['input'],payload)
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                self.assertEqual(outsider.delete(url).status_code,404)
                self.assertEqual(owner.delete(url).status_code,204)
                self.assertEqual(owner.get(url).status_code,404)
                outsider.close()

    def test_streamed_body_limit_is_enforced_before_creating_jobs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ROUTER_API_KEY':'synthetic'}), patch('app.analyze_document',return_value={}):
            with TestClient(create_app(Path(directory)/'test.db'),base_url='http://localhost') as client:
                body=json.dumps({'text':'Документ для проверки ограничения тела','extra':'x'*1100000}).encode()
                request=client.build_request('POST','/api/analyses',headers={'Content-Type':'application/json'},content=iter([body[:400000],body[400000:]]))
                self.assertNotIn('content-length',request.headers)
                self.assertEqual(client.send(request).status_code,413)
                self.assertEqual(client.post('/api/analyses',json={'text':'Документ для проверки ограничения полей','extra':'value'}).status_code,422)

    def test_api_lifecycle_and_private_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ROUTER_API_KEY":"secret-test-value"}), patch("app.analyze_document", return_value={"blocks":[],"risks":[]}):
            app = create_app(Path(directory) / 'test.sqlite3')
            with TestClient(app, base_url='http://localhost') as client:
                health = client.get('/api/health')
                self.assertTrue(health.json()['router_configured'])
                self.assertNotIn('secret-test-value', health.text)
                self.assertEqual(client.post('/api/analyses', json={"text":" "*30}).status_code, 422)
                self.assertEqual(client.post('/api/analyses', headers={"Origin":"https://evil.example"}, json={"text":"Содержательный документ для проверки"}).status_code, 403)
                self.assertEqual(client.get('/api/health', headers={"Host":"evil.example"}).status_code, 400)
                response = client.post('/api/analyses', json={"text":"Содержательный документ для проверки"})
                self.assertEqual(response.status_code, 202)
                for _ in range(100):
                    result = client.get('/api/analyses/' + response.json()['id']).json()
                    if result['status'] == 'done': break
                    time.sleep(.01)
                self.assertEqual(result['status'], 'done')
                self.assertEqual(client.get('/api/analyses/missing').status_code, 404)
            with TestClient(create_app(Path(directory) / 'test.sqlite3'), base_url='http://localhost',cookies=client.cookies) as client:
                self.assertEqual(client.get('/api/analyses/' + response.json()['id']).json()['status'], 'done')


if __name__ == '__main__': unittest.main()

class RetryActionTests(unittest.TestCase):
    def test_explicit_retry_replaces_only_failed_call_and_keeps_successful_steps(self):
        from model_client import ModelError
        attempts=[]
        def analyze(*args,**kwargs):
            client=kwargs['client']
            client('first',{'type':'object'},provider='router')
            data,_=client('second',{'type':'object'},provider='router')
            if not data.get('valid'):
                raise ModelError('Неверная схема результата')
            return {'blocks':[],'risks':[]}
        def remote(url,key,body=None,**kwargs):
            prompt=body['contents'][0]['parts'][0]['text']
            attempts.append(prompt)
            valid=prompt=='first' or attempts.count('second')>1
            return {'id':'job_'+str(len(attempts)),'status':'done','result':{'text':json.dumps({'valid':valid})}}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ROUTER_API_KEY':'synthetic'}),patch('app.analyze_document',side_effect=analyze),patch('model_client._request',side_effect=remote):
            with TestClient(create_app(Path(directory)/'retry.db'),base_url='http://localhost') as client:
                url='/api/analyses/'+client.post('/api/analyses',json={'text':'Документ для проверки явного повторного запроса'}).json()['id']
                for _ in range(100):
                    state=client.get(url).json()
                    if state['status']=='failed':break
                    time.sleep(.01)
                self.assertEqual(state.get('retry_action'),'retry')
                self.assertEqual(client.post(url+'/resume').status_code,409)
                self.assertEqual(client.post(url+'/retry').status_code,202)
                for _ in range(100):
                    state=client.get(url).json()
                    if state['status']=='done':break
                    time.sleep(.01)
                self.assertEqual(state['status'],'done')
                self.assertEqual(attempts,['first','second','second'])

class RetentionTests(unittest.TestCase):
    def test_expired_inactive_jobs_and_model_traces_are_purged_and_history_is_owned(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ROUTER_API_KEY':'synthetic'}),patch('app.analyze_document',return_value={'blocks':[],'risks':[]}):
            app=create_app(Path(directory)/'expiry.db')
            with TestClient(app,base_url='http://localhost') as client:
                job_id=client.post('/api/analyses',json={'text':'Публичный документ для проверки срока хранения'}).json()['id']
                for _ in range(100):
                    if client.get('/api/analyses/'+job_id).json()['status']=='done':break
                    time.sleep(.01)
                history=client.get('/api/analyses')
                self.assertEqual(history.status_code,200)
                self.assertEqual(history.json()['analyses'][0]['id'],job_id)
                outsider=TestClient(app,base_url='http://localhost')
                self.assertEqual(outsider.get('/api/analyses').json()['analyses'],[])
                app.state.db.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?",(job_id,))
                app.state.db.execute('INSERT INTO model_calls VALUES (?,?,?)',(job_id,'trace','{}'))
                app.state.db.commit()
                self.assertEqual(client.get('/api/analyses/'+job_id).status_code,404)
                self.assertEqual(app.state.db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],0)
                outsider.close()
