"""Human review entry controls. The center board and right Kifu stay shared."""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (QWidget,QScrollArea,QVBoxLayout,QFormLayout,QLabel,
    QComboBox,QSpinBox,QPlainTextEdit,QListWidget,QAbstractItemView,QPushButton,
    QHBoxLayout,QCheckBox)


class ReviewPanel(QScrollArea):
    changed = pyqtSignal()
    commit = pyqtSignal()
    save_requested = pyqtSignal()
    load_requested = pyqtSignal()
    leave_requested = pyqtSignal()
    open_review = pyqtSignal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True);self.setMinimumWidth(230)
        content=QWidget();self.setWidget(content);layout=QVBoxLayout(content)
        self.identity=QLabel();self.identity.setWordWrap(True);layout.addWidget(self.identity)
        form=QFormLayout();layout.addLayout(form)
        self.judgement=QComboBox();self.judgement.addItems(['UNKNOWN','ACCEPT','REJECT'])
        form.addRow('Judgement',self.judgement)
        self.reasons=QListWidget();self.reasons.addItems(['Evaluation','Move choice','Tactics','King safety','Material','Rules','Mate claim','Other'])
        self.reasons.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);self.reasons.setMaximumHeight(115)
        form.addRow('Reasons',self.reasons)
        self.confidence=QSpinBox();self.confidence.setRange(0,100);self.confidence.setSpecialValueText('0 - uncertain')
        form.addRow('Confidence %',self.confidence)
        self.notes=QPlainTextEdit();self.notes.setPlaceholderText('Human notes');self.notes.setMaximumHeight(80)
        form.addRow('Notes',self.notes)
        self.mate=QCheckBox('This is mate (human claim)');layout.addWidget(self.mate)
        self.attacker=QComboBox();self.attacker.addItems(['CAM','XANH']);form2=QFormLayout();layout.addLayout(form2);form2.addRow('Attacker',self.attacker)
        self.candidate=QPlainTextEdit();self.candidate.setPlaceholderText('Candidate line (CLP notation)');self.candidate.setMaximumHeight(65);form2.addRow('Candidate line',self.candidate)
        self.defenses=QPlainTextEdit();self.defenses.setPlaceholderText('Defenses / node IDs');self.defenses.setMaximumHeight(65);form2.addRow('Defenses',self.defenses)
        self.verification=QLabel('UNVERIFIED - PENDING_ENGINE_SUPPORT');self.verification.setWordWrap(True);layout.addWidget(self.verification)
        self.progress=QLabel('0 reviews');layout.addWidget(self.progress)
        self.review_selector=QComboBox();self.review_selector.setMinimumContentsLength(10)
        self.review_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.review_selector)
        show=QPushButton('Go to selected review');show.clicked.connect(self.open_review);layout.addWidget(show)
        add=QPushButton('Record review');add.clicked.connect(self.commit);layout.addWidget(add)
        row=QHBoxLayout();layout.addLayout(row)
        for text,signal in [('Save JSONL',self.save_requested),('Load JSONL',self.load_requested)]:
            button=QPushButton(text);button.clicked.connect(signal);row.addWidget(button)
        leave=QPushButton('Leave Training Review');leave.clicked.connect(self.leave_requested);layout.addWidget(leave)
        layout.addStretch()
        for widget,signal in [(self.judgement,'currentTextChanged'),(self.reasons,'itemSelectionChanged'),(self.confidence,'valueChanged'),(self.notes,'textChanged'),(self.mate,'toggled'),(self.attacker,'currentTextChanged'),(self.candidate,'textChanged'),(self.defenses,'textChanged')]:
            getattr(widget,signal).connect(lambda *args:self.changed.emit())

    def values(self):
        return dict(judgement=self.judgement.currentText(),reasons=[i.text() for i in self.reasons.selectedItems()],
                    confidence=self.confidence.value(),notes=self.notes.toPlainText(),
                    mate=dict(claim=self.mate.isChecked(),attacker=self.attacker.currentText(),
                              candidate_line=self.candidate.toPlainText(),defenses=self.defenses.toPlainText(),
                              verification='UNVERIFIED',solver_status='PENDING_ENGINE_SUPPORT'))

    def set_values(self,value):
        widgets=[self.judgement,self.reasons,self.confidence,self.notes,self.mate,self.attacker,self.candidate,self.defenses]
        for w in widgets:w.blockSignals(True)
        try:
            self.judgement.setCurrentText(value.get('judgement','UNKNOWN'))
            for i in range(self.reasons.count()):self.reasons.item(i).setSelected(self.reasons.item(i).text() in value.get('reasons',[]))
            self.confidence.setValue(value.get('confidence',0));self.notes.setPlainText(value.get('notes',''))
            mate=value.get('mate',{});self.mate.setChecked(mate.get('claim',False));self.attacker.setCurrentText(mate.get('attacker','CAM'))
            self.candidate.setPlainText(mate.get('candidate_line',''));self.defenses.setPlainText(mate.get('defenses',''))
        finally:
            for w in widgets:w.blockSignals(False)
