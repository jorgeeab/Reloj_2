/* Widget: pybullet_viewer (Visualización PyBullet con Controles de Cámara) */
(function () {
    function factory(ctx) {
        let refs = null;
        let pollTimer = null;
        let lastFrameUrl = null;
        let cameraState = {
            target: [0, 0, 0.03],
            distance: 0.35,
            yaw: 45,
            pitch: -25,
            up_axis: 2
        };
        let isPending = false;
        let cameraDirty = false;

        function initControl() {
            const canvas = document.getElementById('pybullet_view');
            const status = document.getElementById('pybullet_status');
            if (!canvas || !status) return;

            refs = {
                canvas,
                status,
                distance: document.getElementById('pb_distance'),
                distanceVal: document.getElementById('pb_distance_val'),
                yaw: document.getElementById('pb_yaw'),
                yawVal: document.getElementById('pb_yaw_val'),
                pitch: document.getElementById('pb_pitch'),
                pitchVal: document.getElementById('pb_pitch_val'),
                targetX: document.getElementById('pb_target_x'),
                targetXVal: document.getElementById('pb_target_x_val'),
                targetY: document.getElementById('pb_target_y'),
                targetYVal: document.getElementById('pb_target_y_val'),
                targetZ: document.getElementById('pb_target_z'),
                targetZVal: document.getElementById('pb_target_z_val'),
                saveBtn: document.getElementById('pb_save_view'),
                loadBtn: document.getElementById('pb_load_view'),
                resetBtn: document.getElementById('pb_reset_view')
            };

            // Inicializar valores de los sliders
            initSliders();

            // Bind events a sliders
            bindSlider(refs.distance, refs.distanceVal, (v) => {
                cameraState.distance = parseFloat(v);
                cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            bindSlider(refs.yaw, refs.yawVal, (v) => {
                cameraState.yaw = parseFloat(v);
                cameraDirty = true;
            }, (v) => v + '°');

            bindSlider(refs.pitch, refs.pitchVal, (v) => {
                cameraState.pitch = parseFloat(v);
                cameraDirty = true;
            }, (v) => v + '°');

            bindSlider(refs.targetX, refs.targetXVal, (v) => {
                cameraState.target[0] = parseFloat(v);
                cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            bindSlider(refs.targetY, refs.targetYVal, (v) => {
                cameraState.target[1] = parseFloat(v);
                cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            bindSlider(refs.targetZ, refs.targetZVal, (v) => {
                cameraState.target[2] = parseFloat(v);
                cameraDirty = true;
            }, (v) => parseFloat(v).toFixed(2));

            // Botones
            if (refs.saveBtn) {
                refs.saveBtn.addEventListener('click', async () => {
                    try {
                        await saveView();
                        ctx.toast && ctx.toast('Vista guardada ✓');
                    } catch (err) {
                        ctx.toast && ctx.toast('Error guardando vista');
                        console.error('[PyBullet] Error guardando:', err);
                    }
                });
            }

            if (refs.loadBtn) {
                refs.loadBtn.addEventListener('click', async () => {
                    try {
                        await loadView();
                        ctx.toast && ctx.toast('Vista cargada ✓');
                    } catch (err) {
                        ctx.toast && ctx.toast('No hay vista guardada');
                        console.error('[PyBullet] Error cargando:', err);
                    }
                });
            }

            if (refs.resetBtn) {
                refs.resetBtn.addEventListener('click', () => {
                    resetView();
                    ctx.toast && ctx.toast('Vista reseteada');
                });
            }

            // Configuración de gear
            const gear = document.getElementById('gear_pybullet');
            if (gear && typeof ctx.openSettings === 'function') {
                gear.addEventListener('click', () => ctx.openSettings('cfg_pybullet'));
            }

            // Iniciar loop de actualización de cámara (20Hz)
            setInterval(processCameraUpdate, 50);

            // Iniciar polling de frames
            startPolling();

            // Cargar vista guardada si existe (silenciosamente)
            loadView(true).catch(() => { });

            console.log('PyBullet Viewer v3 loaded');
        }

        function initSettings() {
            const card = document.getElementById('cfg_pybullet');
            if (!card) return;

            const widthInput = document.getElementById('pb_width');
            const heightInput = document.getElementById('pb_height');
            const applyBtn = document.getElementById('pb_apply_size');

            if (applyBtn && widthInput && heightInput) {
                applyBtn.addEventListener('click', async () => {
                    const width = parseInt(widthInput.value) || 1280;
                    const height = parseInt(heightInput.value) || 720;

                    try {
                        const response = await ctx.jpost('/api/pybullet/resize', { width, height });
                        if (response && response.status === 'ok') {
                            ctx.toast && ctx.toast(`Tamaño cambiado a ${response.width}x${response.height}`);
                        }
                    } catch (err) {
                        ctx.toast && ctx.toast('Error cambiando tamaño');
                        console.error('[PyBullet] Error resize:', err);
                    }
                });
            }
        }

        function bindSlider(slider, output, onChange, formatter = (v) => v) {
            if (!slider || !output) return;

            slider.addEventListener('input', () => {
                const val = slider.value;
                output.textContent = formatter(val);
                onChange(val);
            });

            // Inicializar output
            output.textContent = formatter(slider.value);
        }

        function initSliders() {
            if (!refs) return;

            // Obtener config actual del servidor
            getCameraConfig().then(config => {
                if (config) {
                    cameraState = {
                        target: config.target || [0, 0, 0.03],
                        distance: config.distance || 0.35,
                        yaw: config.yaw || 45,
                        pitch: config.pitch || -25,
                        up_axis: config.up_axis || 2
                    };
                    updateSlidersFromState();
                }
            }).catch(() => {
                // Usar valores por defecto
                updateSlidersFromState();
            });
        }

        function updateSlidersFromState() {
            if (!refs) return;

            console.log('[PyBullet] Update sliders:', cameraState);

            refs.distance.value = cameraState.distance;
            refs.distanceVal.textContent = parseFloat(cameraState.distance).toFixed(2);

            refs.yaw.value = cameraState.yaw;
            refs.yawVal.textContent = cameraState.yaw + '°';

            refs.pitch.value = cameraState.pitch;
            refs.pitchVal.textContent = cameraState.pitch + '°';

            refs.targetX.value = cameraState.target[0];
            refs.targetXVal.textContent = parseFloat(cameraState.target[0]).toFixed(2);

            refs.targetY.value = cameraState.target[1];
            refs.targetYVal.textContent = parseFloat(cameraState.target[1]).toFixed(2);

            refs.targetZ.value = cameraState.target[2];
            refs.targetZVal.textContent = parseFloat(cameraState.target[2]).toFixed(2);
        }

        async function getCameraConfig() {
            try {
                const response = await fetch('/api/pybullet/camera');
                if (response.ok) {
                    const data = await response.json();
                    return data.camera;
                }
            } catch (err) {
                console.error('[PyBullet] Error obteniendo config:', err);
            }
            return null;
        }

        async function processCameraUpdate() {
            if (!cameraDirty || isPending) return;
            isPending = true;

            try {
                await ctx.jpost('/api/pybullet/camera', {
                    target: cameraState.target,
                    distance: cameraState.distance,
                    yaw: cameraState.yaw,
                    pitch: cameraState.pitch,
                    up_axis: cameraState.up_axis
                });
            } catch (err) {
                console.error('[PyBullet] Error actualizando cámara:', err);
            } finally {
                isPending = false;
                // Si el usuario siguió moviendo, cameraDirty seguirá true (porque el evento input lo pone true)
                // Si queremos ser estrictos, podríamos poner cameraDirty = false justo antes del await, 
                // pero si falla la petición, quizás queramos reintentar.
                // En este modelo simple, cameraDirty solo indica "hay cambios pendientes de enviar".
                // Al terminar el envío, si no hubo nuevos inputs, cameraDirty debería ser false.
                // Pero como lo seteamos en el evento input, si no hubo input, sigue true desde antes?
                // No, necesitamos resetearlo.

                // Corrección: cameraDirty debe resetearse CUANDO empezamos a enviar, 
                // pero si hay input DURANTE el envío, debe volver a true.
                // Como JS es single threaded, el evento input no interrumpirá este bloque síncrono,
                // pero sí puede ocurrir mientras esperamos el await.
            }
        }

        // Mejor implementación de processCameraUpdate para manejar dirty flag correctamente
        /*
           El patrón correcto es:
           1. Guardar estado actual a enviar.
           2. Marcar dirty = false.
           3. Enviar.
           4. Si falla, marcar dirty = true de nuevo (opcional).
           
           Pero como cameraState es mutable y compartido, si cambia durante el envío, 
           el dirty se pondrá true de nuevo por el evento input.
        */

        async function updateCamera() {
            cameraDirty = true;
            processCameraUpdate();
        }

        // Sobreescribimos processCameraUpdate con lógica correcta de dirty flag
        async function processCameraUpdate() {
            if (!cameraDirty || isPending) return;

            // Snapshot de lo que vamos a enviar (aunque cameraState es obj, sus props primitivas se copian, pero target es array ref)
            // Para simplicidad, enviamos cameraState actual.

            isPending = true;
            cameraDirty = false; // Asumimos que se enviará. Si hay input durante el await, se pondrá true de nuevo.

            try {
                await ctx.jpost('/api/pybullet/camera', {
                    target: cameraState.target,
                    distance: cameraState.distance,
                    yaw: cameraState.yaw,
                    pitch: cameraState.pitch,
                    up_axis: cameraState.up_axis
                });
            } catch (err) {
                console.error('[PyBullet] Error actualizando cámara:', err);
                cameraDirty = true; // Reintentar
            } finally {
                isPending = false;
            }
        }

        async function saveView() {
            const response = await ctx.jpost('/api/pybullet/camera/save', {});
            if (response && response.status === 'ok') {
                return response.camera;
            }
            throw new Error('Error guardando vista');
        }

        async function loadView(silent = false) {
            const response = await ctx.jget('/api/pybullet/camera/load');
            if (response && response.status === 'ok' && response.camera) {
                cameraState = {
                    target: response.camera.target || cameraState.target,
                    distance: response.camera.distance || cameraState.distance,
                    yaw: response.camera.yaw || cameraState.yaw,
                    pitch: response.camera.pitch || cameraState.pitch,
                    up_axis: response.camera.up_axis || cameraState.up_axis
                };
                updateSlidersFromState();
                return response.camera;
            }
            if (!silent) {
                throw new Error('No hay vista guardada');
            }
        }

        function resetView() {
            cameraState = {
                target: [0, 0, 0.03],
                distance: 0.35,
                yaw: 45,
                pitch: -25,
                up_axis: 2
            };
            updateSlidersFromState();
            updateCamera();
        }

        function startPolling() {
            if (pollTimer) return;

            const fetchFrame = async () => {
                try {
                    // Usar timestamp para evitar caché
                    const response = await fetch(`/api/pybullet/frame?ts=${Date.now()}`, { cache: 'no-store' });

                    if (response.status === 503 || response.status === 404) {
                        setStatus('PyBullet no disponible', false);
                        // No paramos polling, reintentamos
                        return;
                    }

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }

                    const blob = await response.blob();
                    if (lastFrameUrl) {
                        URL.revokeObjectURL(lastFrameUrl);
                    }
                    lastFrameUrl = URL.createObjectURL(blob);
                    refs.canvas.src = lastFrameUrl;
                    setStatus('Visualización en vivo', true);
                } catch (err) {
                    setStatus('Esperando frame...', false);
                }
            };

            // Primera carga inmediata
            fetchFrame();

            // Polling cada 40ms (25 FPS) - Muy fluido
            pollTimer = setInterval(fetchFrame, 40);
        }

        function stopPolling() {
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        function setStatus(message, isActive) {
            if (!refs || !refs.status) return;
            refs.status.textContent = message;
            refs.status.style.color = isActive ? '#10b981' : '#9ca3af';
        }

        function onTelemetry(data) {
            // Actualización de telemetría si es necesario
            // Por ahora el visualizador se actualiza automáticamente en el backend
        }

        return {
            initControl,
            initSettings,
            onTelemetry
        };
    }

    if (typeof window !== 'undefined' && window.RelojWidgets) {
        window.RelojWidgets.register('pybullet_viewer', factory);
    }
})();
