"""Consider content installed into STEP 5's existing dock-owned QWidget."""
from PyQt6.QtWidgets import QHBoxLayout,QPushButton,QSpinBox,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView

class ConsiderActions:
    def _init_consider(self):
        self.consider_panel.setMinimumSize(500,260)
        layout=self.consider_panel.layout()
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        row=QHBoxLayout();self.consider_start=QPushButton('Start finite Consider');self.consider_stop=QPushButton('Stop');self.consider_stop.setEnabled(False)
        self.candidate_count=QSpinBox();self.candidate_count.setRange(1,1);self.candidate_count.setEnabled(False)
        self.consider_limit=QSpinBox();self.consider_limit.setRange(100,86400000);self.consider_limit.setValue(3000);self.consider_limit.setSuffix(' ms (finite)')
        for w in (self.consider_start,self.consider_stop,self.candidate_count,self.consider_limit):row.addWidget(w)
        layout.addLayout(row);self.consider_status=QLabel('MultiPV: N/A — select an engine');self.consider_status.setWordWrap(True);layout.addWidget(self.consider_status)
        self.candidate_table=QTableWidget(0,7);self.candidate_table.setHorizontalHeaderLabels(['R','Time','Depth','Nodes','NPS (computed)','Score','PV'])
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.candidate_table.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.candidate_table,1);self.candidate_preview=QLabel('Read-only PV inspection: select a candidate. Board preview is not implemented.');self.candidate_preview.setWordWrap(True);layout.addWidget(self.candidate_preview)
        self.consider_start.clicked.connect(lambda:self._start_inspection('consider'));self.consider_stop.clicked.connect(self._stop_inspection)
        self.candidate_table.itemSelectionChanged.connect(self._inspect_candidate)
        self._live_capabilities=None
        self.engine_controller.metadataReady.connect(self._on_live_capabilities)
        self.analysis_controls.engine.currentIndexChanged.connect(self._consider_selected_engine)
        self._consider_selected_engine()

    def _consider_selected_engine(self):
        from engine import registry
        chosen=self.analysis_controls.engine.currentData();entry=next((e for e in registry.load() if e.get('id',e['path'])==chosen),{})
        # Registry stores option definitions separately from user option values.
        meta=dict(entry);meta['options']=entry.get('option_definitions',{})
        if self._live_capabilities and (entry.get('path'),entry.get('args',[]))==self._live_capabilities[:2]:meta=self._live_capabilities[2]
        self._consider_capabilities(meta)

    def _on_live_capabilities(self, metadata):
        self._live_capabilities=(self.engine_controller.engine_path,self.engine_controller.args,metadata)
        self._consider_capabilities(metadata)

    def _consider_capabilities(self,metadata):
        if not hasattr(self,'candidate_count'):return
        definition=metadata.get('options',{}).get('MultiPV');supported=isinstance(definition,dict) and definition.get('type')=='spin'
        self.candidate_count.setRange(1,min(256,definition['max']) if supported else 1);self.candidate_count.setEnabled(supported and not self.engine_controller.running)
        self._consider_capability_text=('MultiPV: supported, available ranks only' if supported else 'MultiPV: Not supported by current engine')+' | Infinite: PENDING_ENGINE_SUPPORT'
        self.consider_status.setText(self.engine_controller.state+' | '+self._consider_capability_text)
        if not supported:self.engine_controller.options.pop('MultiPV',None)

    def _clear_candidates(self):
        if hasattr(self,'candidate_table'):
            self.candidate_table.setRowCount(0);self.candidate_preview.setText('Read-only PV inspection: N/A')

    def _update_candidates(self,info):
        if not hasattr(self,'candidate_table') or self._inspection_mode!='consider':return
        table=self.candidate_table;rank=info.multipv;row=None
        for i in range(table.rowCount()):
            if table.item(i,0).text()==str(rank):row=i;break
        if row is None:row=table.rowCount();table.insertRow(row)
        score='N/A' if info.score is None else f'{info.score_kind} {info.score} ({info.root_side} root)'
        values=[rank,f'{info.time_ms} ms' if info.time_ms is not None else 'N/A',info.depth,info.nodes,info.nps if info.nps is not None else 'N/A',score,' '.join(info.pv or [])]
        for col,value in enumerate(values):
            item=table.item(row,col)
            if item is None:item=QTableWidgetItem();table.setItem(row,col,item)
            item.setText('N/A' if value is None else str(value))

    def _inspect_candidate(self):
        row=self.candidate_table.currentRow()
        if row>=0:
            item=self.candidate_table.item(row,6)
            if item:self.candidate_preview.setText('Read-only PV (text only): '+item.text())
