class ProtocolRunner {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.select = this.container.querySelector('#protocol-select');
        this.description = this.container.querySelector('#protocol-description');
        this.paramsContainer = this.container.querySelector('#protocol-params-container');
        this.paramsForm = this.container.querySelector('#protocol-params-form');
        this.btnRun = this.container.querySelector('#btn-run-protocol');
        this.btnStop = this.container.querySelector('#btn-stop-protocol');
        this.logContainer = this.container.querySelector('#execution-log');
        this.statusBadge = this.container.querySelector('#runner-status-badge');

        this.protocols = {};
        this.currentExecutionId = null;
        this.pollInterval = null;

        this.init();
    }

    async init() {
        this.select.addEventListener('change', (e) => this.renderParamsForm(e.target.value));
        this.btnRun.addEventListener('click', () => this.runProtocol());
        this.btnStop.addEventListener('click', () => this.stopProtocol());
        await this.loadProtocols();
    }

    async loadProtocols() {
        try {
            const response = await fetch('/api/protocols/list');
            const data = await response.json();

            this.select.innerHTML = '<option value="" selected disabled>Selecciona un protocolo...</option>';
            this.protocols = {};

            if (data.protocols && data.protocols.length > 0) {
                data.protocols.forEach(p => {
                    this.protocols[p.name] = p;
                    const option = document.createElement('option');
                    option.value = p.name;
                    option.textContent = p.name;
                    this.select.appendChild(option);
                });
            } else {
                this.select.innerHTML = '<option value="" disabled>No hay protocolos disponibles</option>';
            }
        } catch (error) {
            console.error('Error cargando protocolos:', error);
            this.select.innerHTML = '<option value="" disabled>Error de conexión</option>';
        }
    }

    renderParamsForm(protocolName) {
        const protocol = this.protocols[protocolName];
        if (!protocol) return;

        this.paramsForm.innerHTML = '';
        this.description.textContent = protocol.description || `Configuración para ${protocolName}`;

        if (protocol.has_parameters && protocol.parameters) {
            this.paramsContainer.style.display = 'block';

            Object.entries(protocol.parameters).forEach(([key, schema]) => {
                const div = document.createElement('div');
                div.className = 'field-group';
                div.style.marginBottom = '10px';

                const label = document.createElement('label');
                label.style.display = 'block';
                label.style.fontSize = '12px';
                label.style.color = 'var(--muted)';
                label.style.marginBottom = '4px';
                label.textContent = schema.label || key;
                div.appendChild(label);

                let input;
                if (schema.type === 'select') {
                    input = document.createElement('select');
                    input.style.width = '100%';
                    input.style.padding = '6px';
                    input.style.borderRadius = '6px';
                    input.style.border = '1px solid var(--border)';
                    input.style.background = 'rgba(0,0,0,0.2)';
                    input.style.color = 'var(--text)';

                    schema.options.forEach(opt => {
                        const option = document.createElement('option');
                        option.value = opt.value;
                        option.textContent = opt.label;
                        if (opt.value == schema.default) option.selected = true;
                        input.appendChild(option);
                    });
                } else if (schema.type === 'boolean') {
                    div.style.display = 'flex';
                    div.style.alignItems = 'center';
                    div.style.gap = '8px';

                    input = document.createElement('input');
                    input.type = 'checkbox';
                    input.checked = schema.default;

                    // Re-order for checkbox
                    label.style.marginBottom = '0';
                    div.innerHTML = ''; // Clear
                    div.appendChild(input);
                    div.appendChild(label);
                } else {
                    input = document.createElement('input');
                    input.type = schema.type === 'number' ? 'number' : 'text';
                    input.style.width = '100%';
                    input.style.padding = '6px';
                    input.style.borderRadius = '6px';
                    input.style.border = '1px solid var(--border)';
                    input.style.background = 'rgba(0,0,0,0.2)';
                    input.style.color = 'var(--text)';

                    if (schema.default !== undefined) input.value = schema.default;
                    if (schema.min !== undefined) input.min = schema.min;
                    if (schema.max !== undefined) input.max = schema.max;
                    if (schema.step !== undefined) input.step = schema.step;
                }

                input.name = key;
                input.id = `param-${key}`;

                if (schema.type !== 'boolean') div.appendChild(input);

                if (schema.description) {
                    const help = document.createElement('div');
                    help.style.fontSize = '11px';
                    help.style.color = 'var(--muted)';
                    help.style.fontStyle = 'italic';
                    help.style.marginTop = '2px';
                    help.textContent = schema.description;
                    div.appendChild(help);
                }

                this.paramsForm.appendChild(div);
            });
        } else {
            this.paramsContainer.style.display = 'none';
        }

        this.btnRun.disabled = false;
    }

    getParams() {
        const params = {};
        const inputs = this.paramsForm.querySelectorAll('input, select');
        inputs.forEach(input => {
            if (input.type === 'checkbox') {
                params[input.name] = input.checked;
            } else if (input.type === 'number') {
                params[input.name] = parseFloat(input.value);
            } else {
                params[input.name] = input.value;
            }
        });
        return params;
    }

    async runProtocol() {
        const protocolName = this.select.value;
        if (!protocolName) return;

        const params = this.getParams();

        this.btnRun.style.display = 'none';
        this.btnStop.style.display = 'inline-block';
        this.statusBadge.textContent = 'Ejecutando';
        this.statusBadge.style.background = 'var(--accent)';
        this.logContainer.innerHTML = '<div style="color:var(--accent)">Iniciando protocolo...</div>';

        try {
            const response = await fetch('/api/tasks/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    protocol_name: protocolName,
                    name: `Manual: ${protocolName}`,
                    params: params,
                    mode: 'async',
                    duration_seconds: 600,
                    timeout_seconds: 600
                })
            });

            const result = await response.json();

            if (response.ok) {
                this.currentExecutionId = result.execution_id;
                this.log(`Iniciado: ID ${this.currentExecutionId}`);
                this.startPolling(this.currentExecutionId);
            } else {
                throw new Error(result.error || 'Error desconocido');
            }
        } catch (error) {
            this.log(`Error: ${error.message}`, 'red');
            this.resetUI();
        }
    }

    async stopProtocol() {
        if (!this.currentExecutionId) return;

        try {
            await fetch(`/api/execution/${this.currentExecutionId}/stop`, { method: 'POST' });
            this.log('Solicitud de parada enviada...', 'orange');
        } catch (error) {
            this.log(`Error al detener: ${error.message}`, 'red');
        }
    }

    startPolling(executionId) {
        if (this.pollInterval) clearInterval(this.pollInterval);

        this.pollInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/execution/${executionId}`);
                if (!response.ok) return;

                const status = await response.json();

                if (status.log && status.log.length > 0) {
                    const lastLog = status.log[status.log.length - 1];
                    if (typeof lastLog === 'string') {
                        this.log(lastLog);
                    } else if (lastLog.message) {
                        this.log(lastLog.message);
                    }
                }

                if (['completed', 'failed', 'stopped', 'timeout'].includes(status.status)) {
                    clearInterval(this.pollInterval);
                    this.log(`Finalizado: ${status.status}`, status.status === 'completed' ? '#4ea1ff' : 'red');
                    this.resetUI();
                }
            } catch (e) {
                console.error("Polling error", e);
            }
        }, 500);
    }

    log(msg, color = 'var(--text)') {
        const div = document.createElement('div');
        div.style.color = color;
        div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        this.logContainer.appendChild(div);
        this.logContainer.scrollTop = this.logContainer.scrollHeight;
    }

    resetUI() {
        this.btnRun.style.display = 'inline-block';
        this.btnStop.style.display = 'none';
        this.statusBadge.textContent = 'Listo';
        this.statusBadge.style.background = 'rgba(255,255,255,0.1)';
        this.currentExecutionId = null;
        if (this.pollInterval) clearInterval(this.pollInterval);
    }
}
