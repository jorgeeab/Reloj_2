/* PyBullet Viewer for Simple Pump Robot */
(function () {
    const PyBulletViewer = {
        pollTimer: null,
        lastFrameUrl: null,
        cameraState: {
            target: [0, 0, 0.03],
            distance: 0.35,
            yaw: 45,
            pitch: -25,
            up_axis: 2
        },
        isPending: false,
        cameraDirty: false,
        updateInterval: null,

        init() {
            this.bindControls();

            // Loop de actualización de cámara (20Hz)
            this.updateInterval = setInterval(() => this.processCameraUpdate(), 50);

            this.startPolling();
            this.loadView(true).catch(() => { });
            console.log('PyBullet Viewer Pump v3 loaded');
        },

        bindControls() {
            // Sliders
            this.bindSlider('pb_distance', 'pb_distance_val', (v) => {
                this.cameraState.distance = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            this.bindSlider('pb_yaw', 'pb_yaw_val', (v) => {
                this.cameraState.yaw = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => v + '°');

            this.bindSlider('pb_pitch', 'pb_pitch_val', (v) => {
                this.cameraState.pitch = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => v + '°');

            this.bindSlider('pb_target_x', 'pb_target_x_val', (v) => {
                this.cameraState.target[0] = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            this.bindSlider('pb_target_y', 'pb_target_y_val', (v) => {
                this.cameraState.target[1] = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            this.bindSlider('pb_target_z', 'pb_target_z_val', (v) => {
                this.cameraState.target[2] = parseFloat(v);
                this.cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            // Buttons
            const saveBtn = document.getElementById('pb_save_view');
            const loadBtn = document.getElementById('pb_load_view');
            const resetBtn = document.getElementById('pb_reset_view');

            if (saveBtn) saveBtn.addEventListener('click', () => this.saveView());
            if (loadBtn) loadBtn.addEventListener('click', () => this.loadView());
            if (resetBtn) resetBtn.addEventListener('click', () => this.resetView());
        },

        bindSlider(sliderId, outputId, onChange, formatter = (v) => v) {
            const slider = document.getElementById(sliderId);
            const output = document.getElementById(outputId);
            if (!slider || !output) return;

            slider.addEventListener('input', () => {
                const val = slider.value;
                output.textContent = formatter(val);
                onChange(val);
            });

            output.textContent = formatter(slider.value);
        },

        async processCameraUpdate() {
            if (!this.cameraDirty || this.isPending) return;

            this.isPending = true;
            this.cameraDirty = false;

            try {
                await fetch('/api/pybullet/camera', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.cameraState)
                });
            } catch (err) {
                console.error('[PyBullet] Error updating camera:', err);
                this.cameraDirty = true; // Reintentar
            } finally {
                this.isPending = false;
            }
        },

        updateCamera() {
            this.cameraDirty = true;
            this.processCameraUpdate();
        },

        async saveView() {
            try {
                const response = await fetch('/api/pybullet/camera/save', { method: 'POST' });
                if (response.ok) {
                    this.showToast('Vista guardada ✓');
                }
            } catch (err) {
                this.showToast('Error guardando vista');
            }
        },

        async loadView(silent = false) {
            try {
                const response = await fetch('/api/pybullet/camera/load');
                if (response.ok) {
                    const data = await response.json();
                    if (data.camera) {
                        this.cameraState = {
                            target: data.camera.target || this.cameraState.target,
                            distance: data.camera.distance || this.cameraState.distance,
                            yaw: data.camera.yaw || this.cameraState.yaw,
                            pitch: data.camera.pitch || this.cameraState.pitch,
                            up_axis: data.camera.up_axis || this.cameraState.up_axis
                        };
                        this.updateSlidersFromState();
                        if (!silent) this.showToast('Vista cargada ✓');
                    }
                }
            } catch (err) {
                if (!silent) this.showToast('No hay vista guardada');
            }
        },

        resetView() {
            this.cameraState = {
                target: [0, 0, 0.03],
                distance: 0.35,
                yaw: 45,
                pitch: -25,
                up_axis: 2
            };
            this.updateSlidersFromState();
            this.updateCamera();
            this.showToast('Vista reseteada');
        },

        updateSlidersFromState() {
            const sliders = {
                pb_distance: this.cameraState.distance,
                pb_yaw: this.cameraState.yaw,
                pb_pitch: this.cameraState.pitch,
                pb_target_x: this.cameraState.target[0],
                pb_target_y: this.cameraState.target[1],
                pb_target_z: this.cameraState.target[2]
            };

            for (const [id, value] of Object.entries(sliders)) {
                const slider = document.getElementById(id);
                if (slider) {
                    slider.value = value;
                    // Actualizar el texto del output manualmente también
                    // para evitar depender del evento input que dispara cameraDirty
                    const outputId = id + '_val';
                    const output = document.getElementById(outputId);
                    if (output) {
                        // Formatear según el tipo
                        if (id.includes('yaw') || id.includes('pitch')) {
                            output.textContent = value + '°';
                        } else {
                            output.textContent = parseFloat(value).toFixed(2);
                        }
                    }
                }
            }
        },

        startPolling() {
            if (this.pollTimer) return;

            const fetchFrame = async () => {
                try {
                    const response = await fetch(`/api/pybullet/frame?ts=${Date.now()}`, { cache: 'no-store' });

                    if (response.status === 503 || response.status === 404) {
                        this.setStatus('PyBullet no disponible', false);
                        // No paramos polling, reintentamos
                        return;
                    }

                    if (!response.ok) throw new Error(`HTTP ${response.status}`);

                    const blob = await response.blob();
                    if (this.lastFrameUrl) URL.revokeObjectURL(this.lastFrameUrl);
                    this.lastFrameUrl = URL.createObjectURL(blob);

                    const img = document.getElementById('pybullet_view');
                    if (img) img.src = this.lastFrameUrl;

                    this.setStatus('Visualización en vivo', true);
                } catch (err) {
                    this.setStatus('Esperando frame...', false);
                }
            };

            fetchFrame();
            // Polling cada 40ms (25 FPS)
            this.pollTimer = setInterval(fetchFrame, 40);
        },

        stopPolling() {
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        },

        setStatus(message, isActive) {
            const status = document.getElementById('pybullet_status');
            if (status) {
                status.textContent = message;
                status.style.color = isActive ? '#10b981' : '#9db3ff';
            }
        },

        showToast(message) {
            const toast = document.getElementById('toast');
            if (toast) {
                toast.textContent = message;
                toast.style.display = 'block';
                setTimeout(() => { toast.style.display = 'none'; }, 3000);
            }
        }
    };

    window.PyBulletViewer = PyBulletViewer;
})();
