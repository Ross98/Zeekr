"""Offline gates: no test invokes launchctl or uses production state."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).parents[1]/'scripts/release'
sys.path.insert(0, str(SCRIPTS))
import macos


class MacReleaseTests(unittest.TestCase):
    def test_names_and_paths_cannot_escape_host(self):
        for name in ('../outside', '', '/tmp/a', 'a/b', '.', '..'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                macos.release_name(name)
        self.assertEqual(macos.release_name('20261021-mini-aabbcc'), '20261021-mini-aabbcc')
        with tempfile.TemporaryDirectory() as folder:
            host = Mock(base=Path(folder).resolve())
            good = dict(candidate=str(host.base/'releases/new'), previous=str(host.base/'releases/old'),
                        backup=str(host.base/'backups/new'))
            macos.check_paths(host, good)
            for key in ('candidate', 'previous', 'backup'):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    macos.check_paths(host, dict(good, **{key: '/tmp/outside'}))

    def test_input_drift_and_new_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); p = root/'zeekr_control/a.py'; p.parent.mkdir(); p.write_text('old')
            expected = macos.public_hashes(root)
            macos.check_hashes(root, expected)
            p.write_text('new')
            with self.assertRaises(ValueError):macos.check_hashes(root, expected)
            p.write_text('old'); (p.parent/'extra.py').write_text('new')
            with self.assertRaises(ValueError):macos.check_hashes(root, expected)

    def test_backup_checks_files_modes_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = parent/'state'; source.mkdir(mode=0o700)
            p=source/'data';p.write_text('private');p.chmod(0o600)
            macos.backup_state(source,parent/'backup')
            self.assertEqual((parent/'backup/data').read_text(),'private')
            self.assertEqual((parent/'backup/data').stat().st_mode & 0o777,0o600)
            (source/'link').symlink_to(p)
            with self.assertRaises(ValueError):macos.backup_state(source,parent/'other')

    def test_verify_failure_rolls_back_without_restoring_business_state(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        host=Mock(base=Path(directory.name));record={'candidate':'candidate'}
        calls=[]
        with patch.object(macos,'preflight'), patch.object(macos,'cutover',side_effect=lambda *_:calls.append('cutover')), \
             patch.object(macos,'verify',side_effect=RuntimeError('unhealthy')), \
             patch.object(macos,'rollback',side_effect=lambda *_:calls.append('rollback')):
            with self.assertRaisesRegex(RuntimeError,'unhealthy'):macos.deploy(host,record)
        self.assertEqual(calls,['cutover','rollback'])

    def test_preflight_failure_never_stops_services_or_rolls_back(self):
        with patch.object(macos,'preflight',side_effect=ValueError('drift')), \
             patch.object(macos,'cutover') as cut,patch.object(macos,'rollback') as undo:
            with self.assertRaises(ValueError):macos.deploy(Mock(),{})
            cut.assert_not_called();undo.assert_not_called()

    def test_failed_stop_prevents_backup_and_switch(self):
        host=Mock();host.stop.side_effect=RuntimeError('still running')
        with patch.object(macos,'backup_state') as backup,patch.object(macos,'switch') as switch:
            with self.assertRaises(RuntimeError):macos.cutover(host,{'backup':'unused','candidate':'unused'})
            backup.assert_not_called();switch.assert_not_called()

    def test_archive_rejects_private_paths_before_writing(self):
        import io,tarfile
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'changes.tar';target=Path(folder)/'candidate';target.mkdir()
            with tarfile.open(archive,'w') as out:
                m=tarfile.TarInfo('zeekr_control/vehicle_profiles.json');m.size=2;out.addfile(m,io.BytesIO(b'{}'))
            with self.assertRaises(ValueError):macos.overlay(archive,target,{'zeekr_control/vehicle_profiles.json':'unused'})
            self.assertEqual(list(target.iterdir()),[])

    def test_atomic_switch_does_not_copy_or_delete_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();old=root/'old';new=root/'new';old.mkdir();new.mkdir()
            link=root/'current';link.symlink_to(old)
            macos.switch(link,new)
            self.assertEqual(link.resolve(),new)
            self.assertTrue(old.is_dir())

    def test_process_parser_uses_only_top_level_launchd_fields(self):
        text='service = {\n\tstate = running\n\tpid = 42\n\truns = 1\n\tsub = {\n\t\tstate = active\n\t}\n}'
        self.assertEqual(macos.job_fields(text),dict(state='running',pid='42',runs='1'))

    def candidate_fixture(self, parent):
        import types
        base=parent/'host';current=base/'releases/old';current.mkdir(parents=True)
        (base/'backups').mkdir();(base/'current').symlink_to(current)
        p=current/'zeekr_control/a.py';p.parent.mkdir();p.write_text('old')
        private=p.parent/'vehicle_profiles.json';private.write_text('private fixture');private.chmod(0o600)
        bundle=parent/'bundle';bundle.mkdir()
        candidate=base/'releases/new'
        config=dict(commit='a'*40,previous=str(current),candidate=str(candidate),backup=str(base/'backups/new'),risk='full')
        baseline=dict(active=str(current),manifest=macos.public_hashes(current),agents={'web':'before'})
        import io,tarfile
        with tarfile.open(bundle/'.release-changes.tar','w') as archive:
            m=tarfile.TarInfo('zeekr_control/a.py');m.size=3;archive.addfile(m,io.BytesIO(b'new'))
        for name,data in [('config',config),('baseline',baseline),('changes',{'zeekr_control/a.py':hashlib.sha256(b'new').hexdigest()})]:
            macos.write(bundle/('.release-'+name+'.json'),data)
        host=Mock(base=base,python='/usr/bin/python3',environment={})
        host.active.return_value=current;host.signature.return_value=baseline['agents']
        host.run.return_value=types.SimpleNamespace(stdout=json.dumps({'status':'recorded','features':[{'status':'matched'}]}))
        return host,bundle,current,candidate

    def test_backend_stage_validates_final_candidate_and_preserves_private_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            host,bundle,current,candidate=self.candidate_fixture(Path(folder).resolve())
            with patch.object(macos.workflow,'validate') as validate:
                macos.stage(host,bundle,True)
            self.assertEqual((candidate/'zeekr_control/a.py').read_text(),'new')
            self.assertEqual((current/'zeekr_control/a.py').read_text(),'old')
            self.assertEqual((candidate/'zeekr_control/vehicle_profiles.json').read_text(),'private fixture')
            self.assertEqual((candidate/'zeekr_control/vehicle_profiles.json').stat().st_mode & 0o777,0o600)
            validate.assert_called_once()
            self.assertEqual(validate.call_args.args[0],candidate)
            self.assertEqual(validate.call_args.args[2],[['/usr/bin/python3','-m','unittest','discover','-s','tests']])
            host.stop.assert_not_called();host.start.assert_not_called()
            self.assertTrue(macos.read(bundle/'.mini-ready.json')['tailscale_ip'])

    def test_failed_candidate_validation_cannot_produce_ready_receipt_or_stop_services(self):
        with tempfile.TemporaryDirectory() as folder:
            host,bundle,_,_=self.candidate_fixture(Path(folder).resolve())
            with patch.object(macos.workflow,'validate',side_effect=RuntimeError('tests failed')):
                with self.assertRaisesRegex(RuntimeError,'tests failed'):macos.stage(host,bundle)
            self.assertFalse((bundle/'.mini-ready.json').exists())
            host.stop.assert_not_called();host.start.assert_not_called()

    def test_stage_stale_baseline_rejected_before_creating_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            host,bundle,current,candidate=self.candidate_fixture(Path(folder).resolve())
            (current/'zeekr_control/a.py').write_text('changed')
            with self.assertRaises(ValueError):macos.stage(host,bundle)
            self.assertFalse(candidate.exists());host.stop.assert_not_called()

    def test_existing_candidate_cannot_leave_stale_ready_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            host,bundle,current,candidate=self.candidate_fixture(Path(folder).resolve())
            macos.write(bundle/'.mini-ready.json',{'stale':True});candidate.mkdir()
            with self.assertRaises(ValueError):macos.stage(host,bundle)
            self.assertFalse((bundle/'.mini-ready.json').exists())

    def test_client_macos_dispatch_never_uses_linux_transport(self):
        import client
        with patch.object(macos,'main') as main,patch.object(client,'remote') as remote, \
             patch('sys.argv',['client.py','macos','inspect']):client.main()
        main.assert_called_once_with(['inspect']);remote.assert_not_called()

    def test_preservation_rejects_lost_personal_records_without_overwriting_state(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();old=root/'backup';new=root/'current'
            for side in (old,new):
                data=side/'Library/Application Support/ZeekrControl';data.mkdir(parents=True)
                (side/'web-auth.json').write_text('synthetic auth')
                (data/'session.json').write_text('synthetic session')
                with sqlite3.connect(data/'personal.sqlite3') as db:
                    db.execute('CREATE TABLE records (owner, vehicle, collection, id, body)')
                    db.execute("INSERT INTO records VALUES ('o','v','tags','id','original')")
            macos.verify_private_state(old,new)
            with sqlite3.connect(new/'Library/Application Support/ZeekrControl/personal.sqlite3') as db:
                db.execute("UPDATE records SET body='changed'")
            with self.assertRaisesRegex(ValueError,'personal record'):macos.verify_private_state(old,new)
            with sqlite3.connect(new/'Library/Application Support/ZeekrControl/personal.sqlite3') as db:
                self.assertEqual(db.execute('SELECT body FROM records').fetchone(),('changed',))

    def test_prepare_exports_only_public_inputs_and_exact_committed_overlay(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();host,_,active,_=self.candidate_fixture(root)
            output=root/'prepared';paths=root/'paths.json';checks=root/'checks.json'
            paths.write_text(json.dumps(['zeekr_control/a.py']));checks.write_text('[]')
            args=SimpleNamespace(output=str(output),name='clean-baseline',paths=str(paths),checks=str(checks),commit='a'*40)
            with patch.object(macos.subprocess,'check_output',return_value=b'new'):
                macos.prepare(host,args)
            self.assertEqual((output/'staged/zeekr_control/a.py').read_bytes(),b'new')
            self.assertFalse((output/'staged/zeekr_control/vehicle_profiles.json').exists())
            self.assertEqual((active/'zeekr_control/a.py').read_bytes(),b'old')
            host.stop.assert_not_called();host.start.assert_not_called()

    def test_agent_environment_merges_without_duplicate_keyword_failure(self):
        host=object.__new__(macos.Host)
        host.environment={'PYTHONDONTWRITEBYTECODE':'0','HOME':'/synthetic-service-home',
                          'HTTPS_PROXY':'http://synthetic-proxy.invalid'}
        with patch.object(macos.subprocess,'run') as run:
            host.run(['/usr/bin/python3','-c','pass'])
        env=run.call_args.kwargs['env']
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'],'1')
        self.assertEqual(env['HOME'],'/synthetic-service-home')
        self.assertEqual(env['HTTPS_PROXY'],'http://synthetic-proxy.invalid')
        self.assertEqual(host.environment['PYTHONDONTWRITEBYTECODE'],'0')

    def password_host(self):
        host=object.__new__(macos.Host)
        host.environment={'PYTHONDONTWRITEBYTECODE':'0','HOME':'/synthetic/state'}
        host.home=Path('/synthetic/state');host.python='/usr/bin/python3';host.domain='gui/501'
        host.active=Mock(return_value=Path('/synthetic/releases/current'))
        return host

    def test_password_change_keeps_password_off_argv_and_restarts_only_web(self):
        password='synthetic changed password'
        with patch.object(macos.sys.stdin,'isatty',return_value=True), \
             patch.object(macos.getpass,'getpass',side_effect=[password,password]), \
             patch.object(macos.subprocess,'run') as run:
            macos.change_password(self.password_host())
        self.assertEqual(run.call_count,2)
        save=run.call_args_list[0]
        self.assertEqual(save.kwargs['input'],password)
        self.assertNotIn(password,' '.join(save.args[0]))
        self.assertEqual(save.kwargs['env']['PYTHONDONTWRITEBYTECODE'],'1')
        self.assertEqual(run.call_args_list[1].args[0],
                         ['launchctl','kickstart','-k','gui/501/local.zeekr.web'])

    def test_password_mismatch_never_writes_or_restarts(self):
        with patch.object(macos.sys.stdin,'isatty',return_value=True), \
             patch.object(macos.getpass,'getpass',side_effect=['synthetic changed password','different password']), \
             patch.object(macos.subprocess,'run') as run:
            with self.assertRaises(ValueError):macos.change_password(self.password_host())
        run.assert_not_called()

    def test_password_restart_failure_reports_already_updated_auth_file(self):
        import subprocess
        with patch.object(macos.sys.stdin,'isatty',return_value=True), \
             patch.object(macos.getpass,'getpass',return_value='synthetic changed password'), \
             patch.object(macos.subprocess,'run',side_effect=[None,subprocess.CalledProcessError(1,['launchctl'])]):
            with self.assertRaisesRegex(ValueError,'密码文件已更新.*重启失败'):
                macos.change_password(self.password_host())

    def test_resource_agent_preserves_service_home_and_keeps_credentials_out_of_arguments(self):
        host=Mock(base=Path('/synthetic/server'),configs={macos.LABELS[1]:{
            'EnvironmentVariables':{'HOME':'/synthetic/server/state','HTTPS_PROXY':'http://synthetic.proxy'},
            'ProgramArguments':['/usr/bin/caffeinate','-s','/usr/bin/python3','-m','zeekr_control','monitor']}})
        config=macos.resource_agent(host)
        self.assertEqual(config['Label'],macos.RESOURCE_LABEL)
        self.assertEqual(config['ProgramArguments'][-1],'zeekr_control.resource_monitor')
        self.assertEqual(config['EnvironmentVariables']['HOME'],'/synthetic/server/state')
        self.assertEqual(config['Nice'],10)
        self.assertNotIn('bark',str(config['ProgramArguments']).lower())

    def test_restore_agents_removes_only_new_resource_agent_on_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);saved=root/'saved';saved.mkdir();agents=root/'agents';agents.mkdir()
            for label in macos.LABELS:
                (saved/(label+'.plist')).write_text('old '+label)
                (agents/(label+'.plist')).write_text('new '+label)
            resource=agents/(macos.RESOURCE_LABEL+'.plist');resource.write_text('new resource')
            unrelated=agents/'unrelated.plist';unrelated.write_text('keep')
            macos.restore_agents(agents,saved)
            self.assertFalse(resource.exists());self.assertEqual(unrelated.read_text(),'keep')
            for label in macos.LABELS:self.assertEqual((agents/(label+'.plist')).read_text(),'old '+label)

    def test_restore_agents_retains_preexisting_resource_agent_on_later_rollbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);saved=root/'saved';saved.mkdir();agents=root/'agents';agents.mkdir()
            for label in (*macos.LABELS,macos.RESOURCE_LABEL):
                (saved/(label+'.plist')).write_text('original')
                (agents/(label+'.plist')).write_text('new')
            macos.restore_agents(agents,saved)
            self.assertEqual((agents/(macos.RESOURCE_LABEL+'.plist')).read_text(),'original')

    def test_stage_resource_installation_is_opt_in_and_does_not_touch_live_agents(self):
        with tempfile.TemporaryDirectory() as folder:
            host,bundle,_,_=self.candidate_fixture(Path(folder).resolve())
            with patch.object(macos.workflow,'validate'):
                macos.stage(host,bundle,resource_monitor=True)
            ready=macos.read(bundle/'.mini-ready.json')
            self.assertTrue(ready['resource_monitor'])
            self.assertTrue(any(call.args[0][1:3]==['-m','zeekr_control.resource_monitor']
                                for call in host.run.call_args_list))
            host.stop.assert_not_called();host.start.assert_not_called()
