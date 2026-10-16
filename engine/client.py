"""Generic CLP-EP v1 QProcess client. No engine-name/algorithm branches."""
import base64,copy,json
import ctypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PyQt6.QtCore import QObject,QProcess,QTimer,QCoreApplication,QThread,pyqtSignal,pyqtSlot
from .protocol import EngineInfo,validate_state,validate_info,simulation,apply_wire,position_id
MAX_LINE=1398200
def split_arguments(command):
    # Parse Windows quoting only; execution always uses QProcess program+args.
    if '\x00' in command or len(command)>8192:raise ValueError('Arguments exceed bound')
    count=ctypes.c_int();parse=ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];parse.restype=ctypes.POINTER(ctypes.c_wchar_p)
    result=parse('"clp" '+command,ctypes.byref(count))
    if not result:raise ValueError('Invalid Windows arguments')
    try:return [result[i] for i in range(1,count.value)]
    finally:
        free=ctypes.windll.kernel32.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p;free(result)
def encode(v):return base64.urlsafe_b64encode(json.dumps(v,ensure_ascii=False,separators=(',',':')).encode('utf8')).decode().rstrip('=')
def decode(token):
    if not token or len(token)>1398102 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in token):raise ValueError('Invalid canonical base64url')
    raw=base64.urlsafe_b64decode(token+'='*((-len(token))%4))
    if len(raw)>1048576 or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=token:raise ValueError('Payload bound/padding bits')
    def pairs(v):
        obj={}
        for k,x in v:
            if k in obj:raise ValueError('Duplicate JSON key')
            obj[k]=x
        return obj
    def reject(v):raise ValueError('Integer-only JSON expected')
    return json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_float=reject,parse_constant=reject)
def _validation(token,kind,state,value,requested):
    try:
        if kind=='state':result=validate_state(state)
        elif kind=='info':result=validate_info(state,value,token[1],requested)
        else:
            move,text=apply_wire(simulation(state),value)
            result={'move':move,'notation':text}
        return token,kind,result,None
    except Exception as exc:return token,kind,None,str(exc)
class Client(QObject):
    stateChanged=pyqtSignal(str);wireSent=pyqtSignal(str);wireReceived=pyqtSignal(str)
    metadataReady=pyqtSignal(object);searchStarted=pyqtSignal();infoReceived=pyqtSignal(object);bestMoveReceived=pyqtSignal(object,str);searchFinished=pyqtSignal(int);errorOccurred=pyqtSignal(str)
    validationFinished=pyqtSignal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.process=None;self.phase='idle';self.generation=0;self.high=0;self.active=0;self.metadata={};self.pending=None;self.buffer=b'';self.stderr=b'';self.stopping=False;self.args=[];self.engine_path='';self.options={};self.requested=1;self.jobs=set();self.info_groups={}
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._deadline)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='clp-validate');self.validationFinished.connect(self._validated);self.latest_info={};self.closed=False;self.state='DISCONNECTED'
    @property
    def phase(self):return getattr(self,'_phase','idle')
    @phase.setter
    def phase(self,value):
        self._phase=value
        state={'search':'SEARCHING','validating':'SEARCHING'}.get(value,'CONNECTING')
        if getattr(self,'stopping',False) and value!='idle':state='STOPPING'
        if value=='idle':
            p=getattr(self,'process',None)
            state='READY' if p is not None and p.state()!=QProcess.ProcessState.NotRunning else 'DISCONNECTED'
        if getattr(self,'state',None)!=state:
            self.state=state;self.stateChanged.emit(state)

    @property
    def running(self):return self.phase!='idle'
    def set_engine_path(self,path,args=None,options=None):
        if self.running:raise RuntimeError('Cannot change executable during an active request')
        path=str(Path(path).resolve());args=list(args or [])
        if self.engine_path!=path or self.args!=args:self._retire()
        self.engine_path=path;self.args=args;self.options=dict(options or {})
    def probe(self,path,args=None):
        if self.running:raise RuntimeError('Probe already active')
        self.set_engine_path(path,args);self.pending={'probe':True};return self._launch()
    def start_search(self,state,move_time_ms=1500,clocks=None):
        if self.closed:self.errorOccurred.emit('Engine client has been closed');return False
        if self.running:self.errorOccurred.emit('Engine busy');return False
        try:
            ms=int(move_time_ms)
            if not 1<=ms<=86400000:raise ValueError('Search time range')
            if clocks is not None and (set(clocks)!=set(('camtime','xanhtime','camperiod','xanhperiod')) or any(type(v)!=int or not 0<=v<=86400000 for v in clocks.values())):raise ValueError('Clock snapshot invalid')
        except Exception as exc:self.errorOccurred.emit(str(exc));return False
        self.pending={'probe':False,'state':copy.deepcopy(state),'ms':ms,'clocks':clocks};self.stopping=False;self.phase='checking'
        self._submit((self.generation,0),'state',self.pending['state'],None,1);self.timer.start(5000);return True
    def _launch(self):
        if not self.engine_path or not Path(self.engine_path).is_file():self._fault('Engine executable missing');return False
        try:
            with open(self.engine_path,'rb') as executable:
                header=executable.read(64)
                if len(header)!=64 or header[:2]!=b'MZ':raise ValueError('Select a Windows executable (.exe); scripts require an interpreter plus arguments')
                offset=int.from_bytes(header[60:64],'little')
                if not 64<=offset<=16777216:raise ValueError('Invalid Windows PE header')
                executable.seek(offset)
                if executable.read(4)!=b'PE\0\0':raise ValueError('Invalid Windows PE signature')
        except (OSError,ValueError) as exc:self._fault(str(exc));return False
        if any(not isinstance(a,str) or '\x00' in a or len(a)>1024 for a in self.args):self._fault('Invalid executable arguments');return False
        self.generation+=1;gen=self.generation;self.high=0;self.active=0;self.buffer=b'';self.stderr=b'';self.metadata={'capabilities':{},'options':{}};self.phase='starting'
        p=QProcess(self);self.process=p;p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        p.started.connect(lambda:self._started(gen));p.readyReadStandardOutput.connect(lambda:self._stdout(gen,p));p.readyReadStandardError.connect(lambda:self._stderr(gen,p));p.finished.connect(lambda c,s:self._finished(gen,c));p.errorOccurred.connect(lambda _:self._process_error(gen,p))
        p.setProgram(self.engine_path);p.setArguments(self.args);p.start();self.timer.start(2000);return True
    def _started(self,gen):
        if gen!=self.generation:return
        self.phase='handshake';self._send('clp 1')
    def _send(self,line):
        if self.process is None or self.process.state()==QProcess.ProcessState.NotRunning:raise RuntimeError('Engine not running')
        self.wireSent.emit(line);self.process.write((line+'\n').encode('utf8'))
    def _stdout(self,gen,p):
        if gen!=self.generation:return
        self.buffer+=bytes(p.readAllStandardOutput())
        while b'\n' in self.buffer:
            raw,self.buffer=self.buffer.split(b'\n',1)
            if len(raw)>MAX_LINE:self._fault('Engine output line exceeds bound');return
            try:self._line(gen,raw.rstrip(b'\r').decode('utf8'))
            except Exception as exc:self._fault('Invalid engine output: '+str(exc));return
            if gen!=self.generation:return
        if len(self.buffer)>MAX_LINE:self._fault('Unterminated engine output exceeds bound')
    def _stderr(self,gen,p):
        if gen==self.generation:self.stderr=(self.stderr+bytes(p.readAllStandardError()))[-8192:]
    def _line(self,gen,line):
        if gen!=self.generation:return
        self.wireReceived.emit(line)
        parts=line.split()
        if not parts:return
        if self.phase=='handshake':
            if line=='clpok':
                if self.metadata.get('protocol')!='clp-ep/1' or not all(self.metadata.get(k) for k in ('name','author','version','kind')):raise ValueError('Incomplete metadata/version handshake')
                self.phase='ready';self._send('isready');self.timer.start(2000);return
            if parts[0]=='id' and len(parts)>=3:
                field=parts[1];value=line.split(' ',2)[2]
                if field in ('name','author','version','kind'):
                    if field in self.metadata or len(value.encode('utf8'))>512 or any(ord(c)<32 for c in value):raise ValueError('Invalid/duplicate metadata')
                    self.metadata[field]=value
            elif parts[0]=='protocol':
                if line!='protocol clp-ep 1':raise ValueError('Unsupported CLP protocol')
                self.metadata['protocol']='clp-ep/1'
            elif parts[0]=='capability' and len(parts)>=3:self.metadata['capabilities'][parts[1]]=parts[2:]
            elif parts[0]=='option' and len(parts)==11 and parts[1]=='name' and parts[3:5]==['type','spin'] and parts[5]=='default' and parts[7]=='min' and parts[9]=='max':
                default,lo,hi=int(parts[6]),int(parts[8]),int(parts[10])
                if not lo<=default<=hi:raise ValueError('Invalid spin option')
                self.metadata['options'][parts[2]]={'type':'spin','default':default,'min':lo,'max':hi}
            elif parts[0]=='error':raise ValueError('Handshake rejected')
            return
        if self.phase=='ready' and line=='readyok':
            self.timer.stop();metadata=copy.deepcopy(self.metadata)
            if self.pending and self.pending['probe']:
                self.phase='idle';self.pending=None;self._retire();self.metadataReady.emit(metadata);return
            self.metadataReady.emit(metadata)
            if gen!=self.generation or self.pending is None:return
            if self.metadata['capabilities'].get('search')!=['legal'] or self.metadata['capabilities'].get('position')!=['rules']:raise ValueError('Engine is not playable with authoritative rules')
            self._begin_search();return
        if parts[0]=='error':
            if len(parts)!=7 or parts[1]!='id' or parts[3]!='code' or parts[5]!='message64':raise ValueError('Malformed error event')
            if int(parts[2]) not in (0,self.active):return
            message=decode(parts[6]);raise ValueError(f"Engine {parts[4]}: {message.get('message','')}")
        if self.phase=='newgame' and line=='newgameok':
            self.phase='position';self._send('position state64 '+encode(self.pending['state']));self.timer.start(5000);return
        if self.phase=='options' and len(parts)==5 and parts[:2]==['optionok','name'] and parts[3]=='value':
            name,value=self._pending_options[0]
            if parts[2]!=name or parts[4]!=str(value):raise ValueError('Mismatched option acknowledgement')
            self._pending_options.pop(0);self._next_option();return
        if self.phase=='position' and len(parts)==3 and parts[:2]==['positionok','generation']:
            if not parts[2].isdigit():raise ValueError('Invalid position generation')
            self.high+=1;self.active=self.high;self.root=self.pending['state'];self.requested=int(self._active_options.get('MultiPV',1));self.info_groups={};self.latest_info={};self.phase='search';self.searchStarted.emit()
            ms=self.pending['ms'];clocks=self.pending['clocks']
            if clocks is None:command=f'go id {self.active} movetime {ms}'
            else:command=f"go id {self.active} camtime {clocks['camtime']} xanhtime {clocks['xanhtime']} camperiod {clocks['camperiod']} xanhperiod {clocks['xanhperiod']} limit {ms}"
            self._send(command);self.timer.start(ms+250);return
        if parts[0] in ('info','bestmove'):
            if len(parts)<4 or parts[1]!='id':raise ValueError('Malformed correlated event')
            id=int(parts[2])
            if id!=self.active or self.phase not in ('search','validating'):return # stale IDs do not mutate game
            if parts[0]=='info':
                if self.phase=='validating' or self.stopping:return
                if len(parts)!=5:raise ValueError('Malformed info')
                value=decode(parts[4])
                if parts[3]=='string64':
                    if not isinstance(value,dict) or set(value)!= {'message'} or not isinstance(value['message'],str) or len(value['message'].encode())>8192:raise ValueError('Invalid info text')
                    return
                if parts[3]!='info64':raise ValueError('Unknown info encoding')
                if len(self.jobs)>=2:
                    if not isinstance(value,dict) or type(value.get('multipv'))!=int or not 1<=value['multipv']<=self.requested:raise ValueError('Invalid queued info rank')
                    self.latest_info[value['multipv']]=value
                else:self._validate_async('info',value)
                return
            if self.phase=='validating':raise ValueError('Duplicate bestmove for active ID')
            self.phase='validating';self.timer.start(5000)
            for value in self.latest_info.values():self._submit((self.generation,self.active),'info',self.root,value,self.requested)
            self.latest_info={}
            if self.stopping:self._complete(None,'');return
            if parts[3]=='move64' and len(parts)==5:self._validate_async('best',decode(parts[4]));return
            if parts[3]=='none' and len(parts)==8 and parts[4:7]==['reason','terminal','result64']:
                value=decode(parts[7])
                if value!=self.root['result'] or value.get('status')!='terminal':raise ValueError('False terminal claim')
                self._complete(None,'');return
            if parts[3:]==['none','reason','stopped']:self._complete(None,'No completed iteration (stopped)');return
            raise ValueError('Playable engine returned no valid move')
        raise ValueError('Unexpected engine output in '+self.phase)
    def _begin_search(self):
        self._active_options={name:d['default'] for name,d in self.metadata.get('options',{}).items()};self._active_options.update(self.options)
        for name,value in self._active_options.items():
            definition=self.metadata.get('options',{}).get(name)
            if not definition or type(value)!=int or not definition['min']<=value<=definition['max']:self._fault('Unsupported/invalid engine option '+name);return
        self._pending_options=list(self._active_options.items());self.phase='options';self._next_option()
    def _next_option(self):
        if self._pending_options:
            name,value=self._pending_options[0];self._send(f'setoption name {name} value {value}');self.timer.start(2000);return
        self.phase='newgame';self._send('newgame');self.timer.start(5000)
    def _validate_async(self,kind,value):
        self._submit((self.generation,self.active),kind,self.root,value,self.requested)
    def _submit(self,token,kind,state,value,requested):
        future=self.pool.submit(_validation,token,kind,state,value,requested);self.jobs.add(future)
        def ready(done):
            try:result=done.result()
            except Exception as exc:result=(token,kind,None,str(exc))
            try:self.validationFinished.emit((done,result))
            except RuntimeError:self.jobs.discard(done) # owning QObject already destroyed
        future.add_done_callback(ready)
    @pyqtSlot(object)
    def _validated(self,result):
        if QThread.currentThread()!=self.thread():raise RuntimeError('Validation callback must run on GUI thread')
        future,result=result;self.jobs.discard(future)
        token,kind,value,error=result
        if kind=='state':
            if token!=(self.generation,0) or self.phase!='checking' or self.stopping:return
            if error:self._fault('Native state validation rejected: '+error);return
            self.pending['state']=value
            if self.process is not None and self.process.state()!=QProcess.ProcessState.NotRunning:self._begin_search()
            else:self._launch()
            return
        if token!=(self.generation,self.active) or self.phase not in ('search','validating') or self.stopping:return
        if error:
            if kind=='info' and 'budget' in error:return # bounded optional information, not a board action
            self._fault('Native validation rejected '+kind+': '+error);return
        if kind=='best':self._complete(value['move'],value['notation']);return
        v=value['info'];score=v['score']
        for (request,depth,rank),other in self.info_groups.items():
            if request==v['id'] and depth==v['depth'] and rank!=v['multipv']:
                if v['pv'] and other['pv']:
                    def identity(move):return {k:x for k,x in move.items() if k!='notation'}
                    if identity(v['pv'][0])==identity(other['pv'][0]):self._fault('Duplicate MultiPV first move');return
                if score['kind']==other['score']['kind'] and score['kind']!='mate':
                    if (rank<v['multipv'] and other['score']['value']<score['value']) or (rank>v['multipv'] and other['score']['value']>score['value']):self._fault('Unsorted MultiPV group');return
        self.info_groups[(v['id'],v['depth'],v['multipv'])]=v
        # Keep latest bounded depth/rank groups, not an unbounded search log.
        if len(self.info_groups)>160:self.info_groups={k:self.info_groups[k] for k in sorted(self.info_groups,key=lambda k:(k[1],k[2]),reverse=True)[:160]}
        self.infoReceived.emit(EngineInfo(v['depth'],v['nodes'],v['time_ms'],score['value'],score['kind'],value['notations'],v['multipv'],engine_id=self.metadata.get('name',''),session_id=token,position_id=position_id(self.root),score_perspective=score['perspective'],root_side=self.root['position']['to_move'],nps=(v['nodes']*1000//v['time_ms'] if v['time_ms'] else None),bound=v['bound']))
        if self.phase=='search' and self.latest_info and len(self.jobs)<2:
            rank=next(iter(self.latest_info));self._validate_async('info',self.latest_info.pop(rank))
    def _complete(self,move,text):
        self.timer.stop();self.phase='idle';self.active=0;self.pending=None
        self.bestMoveReceived.emit(move,text);self.searchFinished.emit(0)
    def stop(self):
        if not self.running:return
        self.stopping=True;self.state='STOPPING';self.stateChanged.emit(self.state)
        if self.active and self.process is not None:self._send(f'stop id {self.active}');self.timer.start(500)
        else:self._retire();self.phase='idle';self.pending=None;self.searchFinished.emit(0)
    def close(self):
        self.closed=True;self._retire();self.phase='idle';self.pending=None
        self.pool.shutdown(wait=False,cancel_futures=True)
    def _retire(self):
        self.timer.stop();self.generation+=1;self.active=0
        if self.process is not None:
            p=self.process;self.process=None
            # A probe dialog may be destroyed before async process termination.
            # Detach the retired child and remove callbacks to its former owner.
            for signal in (p.started,p.readyReadStandardOutput,p.readyReadStandardError,p.finished,p.errorOccurred):
                try:signal.disconnect()
                except TypeError:pass
            p.setParent(QCoreApplication.instance())
            if p.state()!=QProcess.ProcessState.NotRunning:
                # Graceful bounded shutdown, callbacks refer only to retired child, never widgets.
                app=QCoreApplication.instance();timer=QTimer(app);timer.setSingleShot(True)
                def force():
                    if p.state()!=QProcess.ProcessState.NotRunning:p.kill()
                def app_quit():
                    force();p.waitForFinished(100)
                def finished(*_):
                    timer.stop();timer.deleteLater()
                    try:app.aboutToQuit.disconnect(app_quit)
                    except (TypeError,RuntimeError):pass
                    p.deleteLater()
                p.finished.connect(finished);timer.timeout.connect(force);app.aboutToQuit.connect(app_quit)
                p.write(b'quit\n');timer.start(500)
            else:p.deleteLater()
    def _fault(self,message):
        was_active=self.running;self._retire();self.phase='idle';self.pending=None;self.state='ERROR';self.stateChanged.emit(self.state);self.errorOccurred.emit(message)
        if was_active:self.searchFinished.emit(1)
    def _deadline(self):
        if self.stopping:self._retire();self.phase='idle';self.pending=None;self.searchFinished.emit(0)
        else:self._fault('Engine timeout in '+self.phase)
    def _finished(self,gen,code):
        if gen!=self.generation:return
        if self.running:self._fault('Engine exited unexpectedly: '+str(code))
        else:self._retire()
    def _process_error(self,gen,p):
        if gen==self.generation:self._fault('Engine process error: '+p.errorString())
