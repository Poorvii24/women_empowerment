document.addEventListener('DOMContentLoaded', function () {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    // ------------------------------------------------------------------------
    // "Why We Found This Skill" Panel
    // ------------------------------------------------------------------------
    // Renders a small collapsible <details> block that explains, in plain
    // language, which skill was recognised, which of the user's own words
    // led us there, and how sure we are — never raw ML terminology (no
    // "similarity score", "embedding", "confidence %"), and never a
    // developer-facing message like an error code or a "pip install..."
    // instruction. Falls back to nothing (returns '') if semantic_analysis
    // is missing, so older cached responses or partial failures never break
    // the feed card.
    function confidenceToPlainLanguage(pct) {
        const i18n = window.OPP_I18N || {};
        if (pct >= 75) return i18n.confHigh || "We're quite sure about this one";
        if (pct >= 45) return i18n.confMed || "We're fairly confident about this one";
        return i18n.confLow || "We think this might apply — tell us more if it doesn't sound right";
    }

    function buildExplainabilityHtml(semanticAnalysis, fusionMethod, geminiErrorDetail, nlpErrorDetail) {
        const i18n = window.OPP_I18N || {};
        if (!semanticAnalysis || !semanticAnalysis.primary) return '';
        const p = semanticAnalysis.primary;

        const otherMatches = (semanticAnalysis.top_matches || []).slice(1).map(m =>
            `<li>${m.skill}</li>`
        ).join('');

        // Friendly, non-technical messages only. Raw API error strings,
        // stack traces, error codes, or developer instructions are never
        // shown to the person using the app.
        const errorRows = [];
        if (geminiErrorDetail) {
            let friendlyMsg = i18n.errGeminiDefault || "We're using our backup way of understanding your story right now — everything still works.";
            if (geminiErrorDetail.includes('invalid_format') || geminiErrorDetail.includes('AIza')) {
                friendlyMsg = i18n.errGeminiConfig || "Something needs attention on our end — please let us know if this keeps happening.";
            } else if (geminiErrorDetail.includes('RESOURCE_EXHAUSTED') || geminiErrorDetail.includes('quota')) {
                friendlyMsg = i18n.errGeminiQuota || "We've reached today's limit for our fastest AI helper, so we're using our backup one instead.";
            } else if (geminiErrorDetail.includes('not set') || geminiErrorDetail.includes('not configured')) {
                friendlyMsg = i18n.errGeminiOffline || "We're working in offline mode right now — everything still works, just a little differently.";
            }
            errorRows.push(`<div class="text-muted small"><i class="bi bi-info-circle me-1"></i>${friendlyMsg}</div>`);
        }
        if (nlpErrorDetail) {
            errorRows.push(`<div class="text-muted small"><i class="bi bi-info-circle me-1"></i>${i18n.errNlp || "We're having trouble understanding this one right now. Try again in a moment, or describe it a little differently."}</div>`);
        }
        const errorHtml = errorRows.length
            ? `<div class="mt-1 p-2" style="background:#fffbea;border-radius:6px;border:1px solid #fde68a;">${errorRows.join('')}</div>`
            : '';

        return `
            <details class="ai-explainability mt-2 small text-muted">
                <summary class="text-primary" style="cursor:pointer;">
                    <i class="bi bi-info-circle me-1"></i>${i18n.whyFoundSkill || 'Why we found this skill'}
                </summary>
                <div class="mt-2 ps-2 border-start">
                    <div><strong>${i18n.skillRecognised || 'Skill we recognised:'}</strong> ${p.skill}</div>
                    <div><strong>${i18n.howSureWeAre || 'How sure we are:'}</strong> ${confidenceToPlainLanguage(p.confidence_pct)}</div>
                    <div><strong>${i18n.whatYouToldUs || 'What you told us that led us here:'}</strong> “${p.matched_phrase}”</div>
                    ${otherMatches ? `<div class="mt-1"><strong>${i18n.weAlsoConsidered || 'We also considered:'}</strong><ul class="mb-0">${otherMatches}</ul></div>` : ''}
                    ${errorHtml}
                </div>
            </details>
        `;
    }

    // ------------------------------------------------------------------------
    // Theme Toggle Logic
    // ------------------------------------------------------------------------
    const themeToggleBtn = document.getElementById('theme-toggle');
    const htmlEl = document.documentElement;

    // NOTE: must be data-bs-theme, not data-theme — every dark-mode rule in
    // styles.css (and career.html's own toggle) is keyed off data-bs-theme.
    // The old data-theme attribute here never matched any CSS selector, so
    // toggling on the Dashboard silently did nothing.
    let isDark = localStorage.getItem('isis-theme') === 'dark';
    htmlEl.setAttribute('data-bs-theme', isDark ? 'dark' : 'light');
    themeToggleBtn.innerHTML = isDark ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-stars"></i>';

    themeToggleBtn.addEventListener('click', () => {
        isDark = !isDark;
        localStorage.setItem('isis-theme', isDark ? 'dark' : 'light');
        htmlEl.setAttribute('data-bs-theme', isDark ? 'dark' : 'light');
        themeToggleBtn.innerHTML = isDark ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-stars"></i>';
        updateChartTheme(isDark);
    });

    // ------------------------------------------------------------------------
    // Notification Bell Logic
    // ------------------------------------------------------------------------
    const notifDot = document.getElementById('notifDot');
    const notifDropdown = document.getElementById('notifDropdown');
    const notifEmpty = document.getElementById('notifEmpty');
    const notifBell = document.getElementById('notifBell');

    function checkNotificationCount() {
        fetch('/notifications/count')
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data && data.unread_count > 0) {
                    notifDot?.classList.remove('d-none');
                } else {
                    notifDot?.classList.add('d-none');
                }
            })
            .catch(() => { });
    }

    // Poll for new notifications every 30 seconds
    checkNotificationCount();
    setInterval(checkNotificationCount, 30000);

    // Fetch and render notifications when the bell dropdown opens
    if (notifBell) {
        notifBell.addEventListener('show.bs.dropdown', function () {
            fetch('/notifications')
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    notifDot?.classList.add('d-none'); // clear dot after open
                    if (!data || !data.notifications || data.notifications.length === 0) {
                        if (notifEmpty) notifEmpty.style.display = 'block';
                        return;
                    }
                    if (notifEmpty) notifEmpty.style.display = 'none';

                    // Remove old items (keep header + empty)
                    notifDropdown.querySelectorAll('.notif-item').forEach(el => el.remove());

                    data.notifications.forEach(n => {
                        const li = document.createElement('li');
                        li.className = 'notif-item';
                        li.innerHTML = `
                            <a class="dropdown-item small py-2 px-3 border-bottom ${n.is_read ? 'text-muted' : 'fw-semibold'}" href="${n.link}">
                                <i class="bi bi-lightning-charge text-warning me-2"></i>${n.message}
                                <span class="d-block text-muted" style="font-size:0.7rem">${new Date(n.created_at).toLocaleString()}</span>
                            </a>`;
                        notifDropdown.appendChild(li);
                    });
                })
                .catch(() => { });
        });
    }

    // ------------------------------------------------------------------------
    // Elements
    // ------------------------------------------------------------------------
    const analyzeBtn = document.getElementById('analyzeBtn');
    const activityInput = document.getElementById('activityInput');
    const leadershipVal = document.getElementById('leadershipVal');
    const employabilityVal = document.getElementById('employabilityVal');
    const leadershipPath = document.getElementById('leadershipPath');
    const employabilityPath = document.getElementById('employabilityPath');
    const resumeFeedContainer = document.getElementById('resumeFeedContainer');
    const emptyFeedState = document.getElementById('emptyFeedState');
    const downloadPdfBtn = document.getElementById('downloadPdfBtn');

    // Feed deduplication — track every resume_snippet already rendered in this
    // session so re-submissions and page-load repopulation never stack duplicates.
    const _renderedSnippets = new Set();

    // ------------------------------------------------------------------------
    // Voice Assistant (Web Speech API)
    // ------------------------------------------------------------------------
    const btnListenOpps = document.getElementById('btnListenOpps');
    const iconListenOpps = document.getElementById('iconListenOpps');

    // Language mapping for Web Speech API
    let speechLang = 'en-US';
    const docLang = document.documentElement.lang;
    if (docLang === 'hi') speechLang = 'hi-IN';
    if (docLang === 'kn') speechLang = 'kn-IN';

    // 1. Speech-to-Text (Microphone) - Attach to all inputs
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const allMicBtns = document.querySelectorAll('.mic-btn, #micBtn1'); // Catch the first one + the new ones

    if (SpeechRecognition) {
        allMicBtns.forEach(btn => {
            const targetInputId = btn.getAttribute('data-target') || 'q1';
            const targetInput = document.getElementById(targetInputId);
            const micIcon = btn.querySelector('i');
            const originalPlaceholder = targetInput ? targetInput.placeholder : "";

            if (!targetInput) return;

            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = speechLang;
            let isRecording = false;

            btn.addEventListener('click', () => {
                if (!isRecording) recognition.start();
                else recognition.stop();
            });

            recognition.onstart = () => {
                isRecording = true;
                btn.classList.remove('btn-outline-secondary', 'text-muted');
                btn.classList.add('btn-danger', 'text-white');
                if (micIcon) micIcon.classList.replace('bi-mic-fill', 'bi-mic-mute-fill');
                targetInput.placeholder = (window.OPP_I18N||{}).listening || "Listening...";
            };

            recognition.onresult = (e) => {
                targetInput.value = e.results[0][0].transcript;
            };

            recognition.onend = () => {
                isRecording = false;
                btn.classList.remove('btn-danger', 'text-white');
                btn.classList.add('btn-outline-secondary', 'text-muted');
                if (micIcon) micIcon.classList.replace('bi-mic-mute-fill', 'bi-mic-fill');
                targetInput.placeholder = originalPlaceholder;
            };

            recognition.onerror = (e) => {
                console.error("Speech recognition error:", e.error);
                recognition.stop();
                btn.classList.remove('btn-danger', 'text-white');
                btn.classList.add('btn-outline-secondary', 'text-muted');
                if (micIcon) micIcon.classList.replace('bi-mic-mute-fill', 'bi-mic-fill');
                targetInput.placeholder = originalPlaceholder;
            };
        });
    } else {
        // Hide all mic buttons if Speech API is unsupported
        allMicBtns.forEach(btn => btn.style.display = 'none');
    }

    // 2. Text-to-Speech (Listen Button)
    window.aiSpeechText = ""; // Holds the dynamic text to read
    if (btnListenOpps) {
        btnListenOpps.addEventListener('click', () => {
            if (!window.aiSpeechText || !window.speechSynthesis) return;

            if (window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
                if (iconListenOpps) {
                    iconListenOpps.classList.replace('bi-volume-up-fill', 'bi-volume-mute-fill');
                    setTimeout(() => iconListenOpps.classList.replace('bi-volume-mute-fill', 'bi-volume-up-fill'), 500);
                }
                return;
            }

            const utterance = new SpeechSynthesisUtterance(window.aiSpeechText);
            utterance.lang = speechLang;

            // Find natural-sounding local voice
            const voices = window.speechSynthesis.getVoices();
            const localVoice = voices.find(v => v.lang.startsWith(speechLang) || v.lang.startsWith(docLang));
            if (localVoice) {
                utterance.voice = localVoice;
            }

            utterance.onstart = () => {
                btnListenOpps.classList.replace('btn-outline-primary', 'btn-primary');
                btnListenOpps.classList.add('text-white');
            };

            utterance.onend = () => {
                btnListenOpps.classList.replace('btn-primary', 'btn-outline-primary');
                btnListenOpps.classList.remove('text-white');
            };

            window.speechSynthesis.speak(utterance);
        });
    }

    // ------------------------------------------------------------------------
    // 5-Point Skill Radar Chart
    // ------------------------------------------------------------------------
    // Single Activity Radar Chart (Step 2)
    const ctx = document.getElementById('skillRadarChart').getContext('2d');

    // Historical Radar Chart (Step 1 Dashboard)
    const historyCtxEl = document.getElementById('historyRadarChart');
    let historyChart;

    // Wizard Elements
    const step1 = document.getElementById('step-1');
    const step2 = document.getElementById('step-2');
    const step3 = document.getElementById('step-3');
    const goToStep3Btn = document.getElementById('goToStep3Btn');
    const restartWizardBtn = document.getElementById('restartWizardBtn');
    const backToStep1Btn = document.getElementById('backToStep1Btn');
    const backToStep2Btn = document.getElementById('backToStep2Btn');

    const radarOptions = (isDark) => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                titleColor: isDark ? '#f8fafc' : '#1e293b',
                bodyColor: isDark ? '#e2e8f0' : '#475569',
                borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                borderWidth: 1,
                padding: 10
            }
        },
        scales: {
            r: {
                min: 0,
                max: 100,
                angleLines: { color: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)' },
                grid: { color: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' },
                ticks: { display: false },
                pointLabels: {
                    color: isDark ? '#94a3b8' : '#64748b',
                    font: { size: 11, family: "'Inter', sans-serif", weight: '600' }
                }
            }
        }
    });

    // Initialize with 0 values
    const skillRadarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: [(window.OPP_I18N||{}).radarPlanning||'Planning Ahead', (window.OPP_I18N||{}).radarMoney||'Managing Money', (window.OPP_I18N||{}).radarProblems||'Handling Problems', (window.OPP_I18N||{}).radarTeam||'Working With Others', (window.OPP_I18N||{}).radarPeople||'Understanding People'],
            datasets: [{
                label: (window.OPP_I18N||{}).competencyMap||'Competency Map',
                data: [0, 0, 0, 0, 0],
                backgroundColor: 'rgba(99, 102, 241, 0.3)',
                borderColor: '#6366f1',
                pointBackgroundColor: '#ec4899',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#ec4899',
                borderWidth: 2,
                tension: 0.3
            }]
        },
        options: radarOptions(isDark)
    });

    // Display-only mapping — the underlying category names (used as real
    // stored data values and scoring-engine lookup keys, e.g. the
    // leadership_category column) are left untouched; this only warms up
    // what's rendered on the chart itself.
    const _i18nL = window.OPP_I18N || {};
    const FRIENDLY_LEADERSHIP_LABELS = {
        'Decision Making': _i18nL.leadDecisionMaking || 'Making Good Calls',
        'Resource Allocation': _i18nL.leadResourceAllocation || 'Making the Most of What You Have',
        'Strategic Planning': _i18nL.radarPlanning || 'Planning Ahead',
        'Team Coordination': _i18nL.leadTeamCoordination || 'Bringing People Together',
        'Team Development': _i18nL.leadTeamDevelopment || 'Helping Others Grow',
        'Empathy & Crisis Management': _i18nL.leadEmpathyCrisis || 'Staying Calm Under Pressure',
    };
    function toFriendlyLabels(labels) {
        return (labels || []).map(l => FRIENDLY_LEADERSHIP_LABELS[l] || l);
    }

    // Fetch and Initialize Dashboard Metrics (Historical Radar)
    if (historyCtxEl) {
        fetch('/dashboard_metrics')
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (data && data.status === 'success' && data.leadership_radar) {
                    historyChart = new Chart(historyCtxEl.getContext('2d'), {
                        type: 'radar',
                        data: {
                            labels: toFriendlyLabels(data.leadership_radar.labels),
                            datasets: [{
                                label: (window.OPP_I18N||{}).historicalStrength||'Historical Strength',
                                data: data.leadership_radar.data,
                                backgroundColor: 'rgba(16, 185, 129, 0.2)', // emerald green
                                borderColor: 'rgba(16, 185, 129, 1)',
                                pointBackgroundColor: 'rgba(16, 185, 129, 1)',
                                pointBorderColor: '#fff',
                                borderWidth: 2,
                            }]
                        },
                        options: radarOptions(isDark)
                    });
                }
            })
            .catch(err => console.error("Could not load dashboard metrics", err));
    }

    function updateChartTheme(isDark) {
        skillRadarChart.options = radarOptions(isDark);
        skillRadarChart.update();
        if (historyChart) {
            historyChart.options = radarOptions(isDark);
            historyChart.update();
        }
    }

    // ------------------------------------------------------------------------
    // SVG Gauge Animation Helper
    // ------------------------------------------------------------------------
    // The SVG path length is 125.6 (half circumference of r=40).
    function setGaugeValue(pathEl, valEl, value) {
        // Clamp 0-100
        const safeVal = Math.max(0, Math.min(100, isNaN(value) ? 0 : value));

        // Dashoffset: 125.6 is empty (0%), 0 is full (100%)
        const offset = 125.6 - (safeVal / 100) * 125.6;
        pathEl.style.strokeDashoffset = offset;

        // Animate number
        let current = parseInt(valEl.innerText) || 0;
        const target = Math.round(safeVal);
        const duration = 1500;
        const steps = 30;
        const stepTime = duration / steps;
        const increment = (target - current) / steps;

        let stepCount = 0;
        const timer = setInterval(() => {
            current += increment;
            stepCount++;
            valEl.innerText = Math.round(current);
            if (stepCount >= steps) {
                valEl.innerText = target;
                clearInterval(timer);
            }
        }, stepTime);
    }

    // ------------------------------------------------------------------------
    // API Interaction (Analyze Activity)
    // ------------------------------------------------------------------------
    analyzeBtn.addEventListener('click', async function () {
        const q1 = document.getElementById('q1').value.trim();
        const q2 = document.getElementById('q2').value.trim();
        const q3 = document.getElementById('q3').value.trim();
        const q4 = document.getElementById('q4').value.trim();
        const q5 = document.getElementById('q5').value.trim();
        const q6 = document.getElementById('q6').value.trim();
        const q7 = document.getElementById('q7').value.trim();
        const q8 = document.getElementById('q8').value.trim();

        if (!q1) {
            document.getElementById('q1').classList.add('is-invalid');
            setTimeout(() => document.getElementById('q1').classList.remove('is-invalid'), 2000);
            return;
        }

        // Join answers into a descriptive paragraph for the AI
        const parts = [];
        parts.push(`Task led: ${q1}.`);
        if (q2) parts.push(`People coordinated: ${q2}.`);
        if (q3) parts.push(`Time spent: ${q3}.`);
        if (q4) parts.push(`Budget handled: ${q4}.`);
        if (q5) parts.push(`Supplies/Inventory managed: ${q5}.`);
        if (q6) parts.push(`Target audience/Beneficiaries: ${q6}.`);
        if (q7) parts.push(`Conflict handling approach: ${q7}.`);
        if (q8) parts.push(`Hardest part / Main Challenge: ${q8}.`);

        const text = parts.join(' ');

        // Loading State
        const originalText = this.innerHTML;
        this.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Analyzing…';
        this.disabled = true;

        // Show loading progress steps
        const progressEl = document.getElementById('analysisProgress');
        if (progressEl) { progressEl.style.display = 'block'; progressEl.classList.add('active'); }
        animateProgressSteps();

        // Show feed skeleton while waiting
        const feedSkeletonEl = document.getElementById('feedSkeleton');
        if (feedSkeletonEl) feedSkeletonEl.classList.remove('d-none');

        try {
            const response = await fetch('/analyze_activity', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ activity: text })
            });

            const data = await response.json();

            if (response.ok) {
                // Remove empty state if present
                if (emptyFeedState) emptyFeedState.remove();

                // 1) Update Gauges
                setGaugeValue(leadershipPath, leadershipVal, data.leadership_index);
                setGaugeValue(employabilityPath, employabilityVal, data.skill_magnitude);

                // 2) Update 5-Point Radar Map Elements
                // We'll deterministically map the categories to our 5 points just for demo visually:
                // Strategic, Financial, Crisis, Team, Emotional
                const cat = data.leadership_category;
                const newBands = [...skillRadarChart.data.datasets[0].data];

                // Slowly decay old values, and spike the new one
                for (let i = 0; i < 5; i++) { newBands[i] = Math.max(15, newBands[i] * 0.7); }

                let targetIdx = 0;
                if (cat.includes("Strategic")) targetIdx = 0;
                else if (cat.includes("Resource") || cat.includes("Decision")) targetIdx = 1;
                else if (cat.includes("Crisis")) targetIdx = 2;
                else if (cat.includes("Coordination")) targetIdx = 3;
                else targetIdx = 4; // Emotion/Development

                newBands[targetIdx] = Math.min(100, data.skill_magnitude + 15);

                skillRadarChart.data.datasets[0].data = newBands;
                skillRadarChart.update();

                // 3) Push to Resume Feed — LinkedIn-style polished card
                const feedEmptyEl    = document.getElementById('emptyFeedState');
                const feedSkeletonEl = document.getElementById('feedSkeleton');
                const feedContainer  = document.getElementById('resumeFeedContainer');
                const feedCountEl    = document.getElementById('feedCount');

                if (feedEmptyEl)    feedEmptyEl.classList.add('d-none');
                if (feedSkeletonEl) feedSkeletonEl.classList.add('d-none');
                if (feedContainer)  feedContainer.classList.remove('d-none');

                const badgeVariants = ['','badge-success','badge-warning','badge-info','badge-pink'];
                const bv = badgeVariants[Math.floor(Math.random() * badgeVariants.length)];
                const skillsHtml = (data.skills_mapped || []).map(s =>
                    `<span class="skill-badge ${bv}">${s}</span>`
                ).join('');

                const explainabilityHtml = buildExplainabilityHtml(
                    data.semantic_analysis, data.fusion_method,
                    data.gemini_error_detail, data.nlp_error_detail
                );

                const bulletText = data.resume_snippet || '';
                const isLong = bulletText.length > 160;
                const shortText = isLong ? bulletText.substring(0,160) + '…' : bulletText;

                if (!_renderedSnippets.has(bulletText)) {
                    _renderedSnippets.add(bulletText);
                    const df = document.createDocumentFragment();
                    const div = document.createElement('div');
                    div.className = 'feed-card';
                    div.setAttribute('role','article');
                    div.innerHTML = `
                        <div class="feed-card-header">
                            <span class="feed-skill-title">
                                <i class="bi bi-briefcase-fill me-1" aria-hidden="true"></i>${data.transferable_skill || 'Professional Skill'}
                            </span>
                            <span class="value-chip" style="background:rgba(16,185,129,0.1);color:#059669;flex-shrink:0;font-size:0.68rem;padding:3px 9px;border-radius:20px;font-weight:600;">
                                <i class="bi bi-graph-up me-1" aria-hidden="true"></i>${data.market_value || 'High'} Value
                            </span>
                        </div>
                        <p class="feed-bullet mb-2">
                            <span class="bullet-short">${shortText}</span>
                            ${isLong ? `<span class="bullet-full d-none">${bulletText}</span>` : ''}
                        </p>
                        ${isLong ? `<button class="feed-expand-btn mb-2" onclick="toggleBullet(this)" aria-expanded="false">Show more <i class="bi bi-chevron-down" aria-hidden="true"></i></button>` : ''}
                        ${skillsHtml ? `<div class="feed-badges">${skillsHtml}</div>` : ''}
                        ${explainabilityHtml}
                    `;
                    df.appendChild(div);
                    if (feedContainer) feedContainer.prepend(df);
                }

                const currentCount = feedContainer ? feedContainer.querySelectorAll('.feed-card').length : 0;
                if (feedCountEl && currentCount > 0) {
                    feedCountEl.textContent = currentCount + ' bullet' + (currentCount !== 1 ? 's' : '');
                    feedCountEl.classList.remove('d-none');
                }

                // 5) Render Smart Matches (deduplicated by title)
                if (data.matches && data.matches.length > 0) {
                    const smContainer = document.getElementById('smartMatchesContainer');
                    const smRow = document.getElementById('smartMatchesRow');
                    if (smContainer && smRow) {
                        smContainer.style.display = 'block';
                        const colours = ['text-primary', 'text-success', 'text-warning', 'text-info-emphasis'];

                        data.matches.forEach((m, idx) => {
                            // Deduplicate by title across all renders on this page
                            if (window._seenMatchTitles && window._seenMatchTitles.has(m.title)) return;
                            if (!window._seenMatchTitles) window._seenMatchTitles = new Set();
                            window._seenMatchTitles.add(m.title);

                            const pct = m.match_percentage || 75;
                            let badgeCls = 'bg-success';
                            if (pct < 70) badgeCls = 'bg-warning text-dark';
                            if (pct < 60) badgeCls = 'bg-secondary';
                            const col = colours[idx % colours.length];

                            const card = document.createElement('div');
                            card.className = 'col-md-6';
                            const pctColor = pct >= 80 ? '#10b981' : pct >= 65 ? '#f59e0b' : '#6366f1';
                            card.innerHTML = `
                                <div class="card h-100 border-0 shadow-sm hover-lift animated-card match-card" style="animation-delay: ${0.1 + idx * 0.15}s; border-left-color:${pctColor} !important;">
                                    <div class="card-body p-4">
                                        <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                                            <h6 class="fw-bold mb-0" style="color:${pctColor}">${m.title}</h6>
                                            <div class="match-ring" style="border-color:${pctColor};color:${pctColor};width:48px;height:48px;font-size:0.72rem;flex-shrink:0;">
                                                ${pct}%
                                            </div>
                                        </div>
                                        <p class="small text-muted mb-3" style="line-height:1.5;">${m.why_it_fits}</p>
                                        <div class="p-2 rounded-3" style="background:rgba(99,102,241,0.06);">
                                            <p class="small fw-semibold mb-0 text-primary"><i class="bi bi-arrow-right-circle-fill me-1"></i>${m.action_step}</p>
                                        </div>
                                    </div>
                                </div>`;
                            smRow.appendChild(card);
                        });
                    }
                }

                // 4) Update Opportunity Engine
                // -------------------------------------------------------------------
                // Read from guaranteed top-level flat keys first (set by backend),
                // then fall back to nested market_opportunities as a second safety net.
                // -------------------------------------------------------------------
                const opps = (data.market_opportunities && typeof data.market_opportunities === 'object')
                    ? data.market_opportunities
                    : {};

                const startupText = String(data.startup_idea || opps.startup_idea || (window.OPP_I18N||{}).analyzingActivityFallback || "Analyzing your activity...");
                const startupBudget = String(data.startup_budget || opps.startup_budget || "₹10,000 – ₹25,000");
                const collabText = String(data.collaboration_match || opps.collaboration_match || (window.OPP_I18N||{}).generatingMatchFallback || "Generating your match...");
                const jobRoleText = String(data.job_role || opps.job_role || "Public Health Outreach Coordinator");

                // Growth Card — flat keys are guaranteed non-empty from backend
                const skillToLearn = String(data.growth_skill || (data.learning_path && data.learning_path.skill_to_learn) || "Digital Literacy & Community Health Communication");
                const freeResource = String((data.learning_path && data.learning_path.free_resource) || "Google Digital Garage on YouTube");
                const dailyGoal = String((data.learning_path && data.learning_path.daily_goal) || "Watch a 10-minute video today");
                const learningUrl = String(data.learning_url || opps.learning_url || "https://www.youtube.com/watch?v=Xv1tM_pX22Y");

                // Populate Dynamic Business Roadmap Modal
                const industryName = data.industry || "Business";
                const bpModalLabel = document.getElementById('businessPlanModalLabel');
                if (bpModalLabel) {
                    bpModalLabel.innerHTML = `<i class="bi bi-rocket-takeoff-fill text-success me-2"></i>Your 3-Step ${industryName} Roadmap`;
                }

                if (opps.business_roadmap && Array.isArray(opps.business_roadmap)) {
                    opps.business_roadmap.forEach((stepObj, idx) => {
                        const stepNum = idx + 1;
                        if (stepNum <= 3) {
                            const titleEl = document.getElementById(`bp-step${stepNum}-title`);
                            const descEl = document.getElementById(`bp-step${stepNum}-desc`);
                            if (titleEl) titleEl.innerText = stepObj.title || `Step ${stepNum}`;
                            if (descEl) descEl.innerText = stepObj.desc || "Action details pending...";
                        }
                    });
                }

                // Populate Dynamic Pitch Email Modal
                if (opps.pitch_email && typeof opps.pitch_email === 'object') {
                    const subjectEl = document.getElementById('pitch-subject');
                    const bodyEl = document.getElementById('pitch-body');
                    if (subjectEl) subjectEl.innerText = opps.pitch_email.subject || "Partnership Proposal";
                    if (bodyEl) bodyEl.innerText = opps.pitch_email.body || "I would love to discuss a potential partnership based on my recent community operations experience. Please let me know if you are open to a brief call.";
                }

                const oppContainer = document.getElementById('opportunityEngineContainer');
                const oppRow = document.getElementById('opportunitiesRow');
                oppContainer.style.removeProperty('display');
                oppContainer.style.display = 'block';

                const matchScore = data.employability_score || 70;
                const matchColor = matchScore >= 80 ? '#10b981' : matchScore >= 60 ? '#f59e0b' : '#6366f1';

                const i18n = window.OPP_I18N || {
                    startup: "Startup Idea", collab: "Collaboration Match", jobRoles: "Specific Job Roles", growth: "Growth Plan",
                    match: "Match", btnStart: "Learn How to Start", btnPitch: "Draft a Pitch", btnDetails: "View Openings", btnLearn: "Start Learning"
                };

                window.aiSpeechText = `${i18n.startup}: ${startupText}. ${i18n.jobRoles}: ${jobRoleText}.`;

                const waBtn = document.getElementById('whatsappShareBtn');
                if (waBtn) {
                    const shareText = `Hi! I just mapped my professional skills with ISIS. I am a ${matchScore}% match for ${jobRoleText}. ${window.location.origin}`;
                    waBtn.href = `https://api.whatsapp.com/send?text=${encodeURIComponent(shareText)}`;
                    waBtn.classList.remove('d-none');
                }

                function oppCard({delay, accent, icon, iconColor, title, titleColor, body, meta1Label, meta1Val, meta2Label, meta2Val, btnId, btnClass, btnIcon, btnLabel}) {
                    return `
                    <div class="col-lg-3 col-sm-6">
                        <div class="card h-100 border-0 shadow-sm hover-lift animated-card opp-card" style="animation-delay:${delay}s;">
                            <div class="opp-card-accent" style="background:${accent};"></div>
                            <div class="card-body p-4 d-flex flex-column" style="padding-top:1.2rem !important;">
                                <div class="d-flex align-items-center justify-content-between mb-3">
                                    <div class="d-flex align-items-center gap-2">
                                        <div class="icon-box icon-box-sm" style="background:${accent}22;">
                                            <i class="bi ${icon}" style="color:${iconColor};"></i>
                                        </div>
                                        <span class="fw-bold" style="font-size:0.8rem;color:${titleColor};">${title}</span>
                                    </div>
                                    <div class="match-ring" style="border-color:${matchColor};color:${matchColor};">
                                        ${matchScore}%
                                    </div>
                                </div>
                                <p class="small text-muted mb-3 flex-grow-1" style="line-height:1.55;">${body}</p>
                                <div class="opp-meta mb-3">
                                    <div class="opp-meta-item">
                                        <div class="label-xs">${meta1Label}</div>
                                        <div class="value">${meta1Val}</div>
                                    </div>
                                    <div class="opp-meta-item">
                                        <div class="label-xs">${meta2Label}</div>
                                        <div class="value">${meta2Val}</div>
                                    </div>
                                </div>
                                <button id="${btnId}" class="btn btn-sm ${btnClass} w-100 rounded-pill mt-auto fw-semibold">
                                    <i class="bi ${btnIcon} me-1"></i>${btnLabel}
                                </button>
                            </div>
                        </div>
                    </div>`;
                }

                oppRow.innerHTML =
                    oppCard({delay:0.05, accent:'#10b981', icon:'bi-rocket-takeoff-fill', iconColor:'#10b981', title:i18n.startup,
                        titleColor:'#059669', body:startupText, meta1Label:i18n.estBudget||'Est. Budget', meta1Val:startupBudget,
                        meta2Label:i18n.impact||'Impact', meta2Val:i18n.lowRiskStart||'Low Risk Start', btnId:'btn-learn-startup',
                        btnClass:'btn-outline-success', btnIcon:'bi-arrow-right-circle', btnLabel:i18n.btnStart}) +
                    oppCard({delay:0.15, accent:'#6366f1', icon:'bi-people-fill', iconColor:'#6366f1', title:i18n.collab,
                        titleColor:'#6366f1', body:collabText, meta1Label:i18n.metaType||'Type', meta1Val:i18n.partnership||'Partnership',
                        meta2Label:i18n.difficulty||'Difficulty', meta2Val:i18n.medium||'Medium', btnId:'btn-draft-pitch',
                        btnClass:'btn-outline-primary', btnIcon:'bi-envelope-paper-fill', btnLabel:i18n.btnPitch}) +
                    oppCard({delay:0.25, accent:'#3b82f6', icon:'bi-person-badge-fill', iconColor:'#3b82f6', title:i18n.jobRoles,
                        titleColor:'#1d4ed8', body:jobRoleText, meta1Label:i18n.timeToApply||'Time to Apply', meta1Val:i18n.oneToTwoDays||'1–2 Days',
                        meta2Label:i18n.skillsGained||'Skills Gained', meta2Val:i18n.leadershipPM||'Leadership + PM', btnId:'btn-view-openings',
                        btnClass:'btn-outline-info', btnIcon:'bi-search', btnLabel:i18n.btnDetails}) +
                    oppCard({delay:0.35, accent:'#f59e0b', icon:'bi-lightning-charge-fill', iconColor:'#d97706', title:i18n.growth,
                        titleColor:'#92400e', body:`<strong>${skillToLearn}</strong><br><span class='text-muted' style='font-size:0.78rem;'>${freeResource}</span><br><em class='text-warning-emphasis' style='font-size:0.75rem;'>${dailyGoal}</em>`,
                        meta1Label:i18n.duration||'Duration', meta1Val:i18n.thirtyDays||'30 Days', meta2Label:i18n.difficulty||'Difficulty', meta2Val:i18n.beginner||'Beginner',
                        btnId:'btn-start-learning', btnClass:'btn-outline-warning', btnIcon:'bi-play-circle-fill', btnLabel:i18n.btnLearn});

                // ----------------------------------------------------------------
                // Action Trigger: Wire button events after innerHTML is injected
                // ----------------------------------------------------------------
                // 1) 'Learn How to Start' → opens 3-step Business Plan popup
                const btnLearnStartup = document.getElementById('btn-learn-startup');
                if (btnLearnStartup) {
                    btnLearnStartup.addEventListener('click', () => {
                        const modal = new bootstrap.Modal(document.getElementById('businessPlanModal'));
                        modal.show();
                    });
                }

                // 2) 'Draft a Pitch' → opens pre-filled email template popup
                const btnDraftPitch = document.getElementById('btn-draft-pitch');
                if (btnDraftPitch) {
                    btnDraftPitch.addEventListener('click', () => {
                        const modal = new bootstrap.Modal(document.getElementById('pitchModal'));
                        modal.show();
                    });
                }

                // 3) 'View Openings' → opens the LinkedIn search URL
                const btnViewOpenings = document.getElementById('btn-view-openings');
                if (btnViewOpenings) {
                    btnViewOpenings.addEventListener('click', () => {
                        if (data.job_link) {
                            window.open(data.job_link, '_blank');
                        }
                    });
                }

                // 4) 'Start Learning' → uses the dynamic YouTube search URL from backend
                const btnStartLearning = document.getElementById('btn-start-learning');
                if (btnStartLearning) {
                    btnStartLearning.addEventListener('click', () => {
                        if (data.learning_link) {
                            window.open(data.learning_link, '_blank');
                        } else {
                            // Sub-fallback if old backend response format
                            const watchUrl = learningUrl.replace('/embed/', '/watch?v=');
                            window.open(watchUrl, '_blank');
                        }
                    });
                }

                // 5) 'Copy' button in Pitch Modal → copies email body to clipboard
                const copyPitchBtn = document.getElementById('copyPitchBtn');
                if (copyPitchBtn) {
                    copyPitchBtn.addEventListener('click', () => {
                        const pitchText = document.getElementById('pitchEmailBody')?.innerText || '';
                        navigator.clipboard.writeText(pitchText).then(() => {
                            copyPitchBtn.innerHTML = '<i class="bi bi-clipboard-check me-1"></i>Copied!';
                            copyPitchBtn.classList.replace('btn-outline-secondary', 'btn-success');
                            setTimeout(() => {
                                copyPitchBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copy';
                                copyPitchBtn.classList.replace('btn-success', 'btn-outline-secondary');
                            }, 2000);
                        });
                    });
                }

                // Inputs are no longer cleared so the user can go back and edit them later.

                this.innerHTML = '<i class="bi bi-check2-circle me-2"></i>Analyzed';
                this.classList.replace('btn-primary', 'btn-success');
                this.style.animation = 'successPulse 0.6s ease';

                // Hide progress steps
                const progressEl = document.getElementById('analysisProgress');
                if (progressEl) { progressEl.classList.remove('active'); progressEl.style.display = 'none'; }

                // Transition to Step 2
                setTimeout(() => {
                    step1.style.display = 'none';
                    step2.style.display = 'block';
                    this.innerHTML = originalText;
                    this.classList.replace('btn-success', 'btn-primary');
                    this.style.animation = '';
                    this.disabled = false;
                }, 900);

            } else {
                alert(`Error: ${data.message}`);
                const progressEl = document.getElementById('analysisProgress');
                if (progressEl) { progressEl.classList.remove('active'); progressEl.style.display = 'none'; }
                this.innerHTML = originalText;
                this.disabled = false;
            }

        } catch (error) {
            console.error(error);
            alert((window.OPP_I18N||{}).networkError || "Network error connecting to Backend.");
            const progressEl = document.getElementById('analysisProgress');
            if (progressEl) { progressEl.classList.remove('active'); progressEl.style.display = 'none'; }
            this.innerHTML = originalText;
            this.disabled = false;
        }
    });

    // ------------------------------------------------------------------------
    // Wizard Navigation Event Listeners
    // ------------------------------------------------------------------------

    if (backToStep1Btn) {
        backToStep1Btn.addEventListener('click', () => {
            step2.style.display = 'none';
            step1.style.display = 'flex';
        });
    }

    if (backToStep2Btn) {
        backToStep2Btn.addEventListener('click', () => {
            step3.style.display = 'none';
            step2.style.display = 'block';
        });
    }

    if (goToStep3Btn) {
        goToStep3Btn.addEventListener('click', () => {
            step2.style.display = 'none';
            step3.style.display = 'block';
        });
    }

    if (restartWizardBtn) {
        restartWizardBtn.addEventListener('click', () => {
            step3.style.display = 'none';

            // Clear inputs ONLY on full Start Over
            document.getElementById('q1').value = '';
            document.getElementById('q2').value = '';
            document.getElementById('q3').value = '';
            document.getElementById('q4').value = '';

            step1.style.display = 'flex'; // It uses d-flex row classes usually
        });
    }

    // ------------------------------------------------------------------------
    // Initial Load - Fetch Dashboard Metrics to Animate Gauges & Load History
    // ------------------------------------------------------------------------
    fetch('/dashboard_metrics')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                if (data.total_activities > 0 && emptyFeedState) {
                    emptyFeedState.remove();
                }

                // 1) Animate Gauges on load
                setGaugeValue(leadershipPath, leadershipVal, data.avg_leadership_index || 0);
                setGaugeValue(employabilityPath, employabilityVal, data.employability_score || 0);

                // 2) Initialize Radar Map Elements
                if (data.radar_averages) {
                    skillRadarChart.data.datasets[0].data = [
                        data.radar_averages['Strategic'] || 0,
                        data.radar_averages['Financial'] || 0,
                        data.radar_averages['Crisis'] || 0,
                        data.radar_averages['Team'] || 0,
                        data.radar_averages['Emotional'] || 0
                    ];
                    skillRadarChart.update();
                }

                // 3) Load recent activity bullets into the Feed
                if (data.recent_activities && data.recent_activities.length > 0) {
                    const feedContainer  = document.getElementById('resumeFeedContainer');
                    const feedEmptyEl    = document.getElementById('emptyFeedState');
                    const feedSkeletonEl = document.getElementById('feedSkeleton');
                    const feedCountEl    = document.getElementById('feedCount');

                    if (feedContainer)  { feedContainer.innerHTML = ''; feedContainer.classList.remove('d-none'); }
                    if (feedEmptyEl)    feedEmptyEl.classList.add('d-none');
                    if (feedSkeletonEl) feedSkeletonEl.classList.add('d-none');
                    _renderedSnippets.clear();

                    const df = document.createDocumentFragment();
                    const badgeVariants = ['','badge-success','badge-warning','badge-info','badge-pink'];

                    data.recent_activities.forEach((act, idx) => {
                        const snippet = act.resume_snippet || `Demonstrated expertise in ${act.mapped_skill}.`;
                        if (_renderedSnippets.has(snippet)) return;
                        _renderedSnippets.add(snippet);

                        const bv = badgeVariants[idx % badgeVariants.length];
                        const skills = Array.isArray(act.skills_mapped) && act.skills_mapped.length > 0
                            ? act.skills_mapped : [];
                        const skillsHtml = skills.map(s => `<span class="skill-badge ${bv}">${s}</span>`).join('');
                        const isLong = snippet.length > 160;
                        const shortText = isLong ? snippet.substring(0,160) + '…' : snippet;

                        const div = document.createElement('div');
                        div.className = 'feed-card';
                        div.setAttribute('role','article');
                        div.innerHTML = `
                            <div class="feed-card-header">
                                <span class="feed-skill-title">
                                    <i class="bi bi-briefcase-fill me-1" aria-hidden="true"></i>${act.mapped_skill || 'Professional Skill'}
                                </span>
                                ${act.market_value ? `<span class="value-chip" style="background:rgba(16,185,129,0.1);color:#059669;flex-shrink:0;font-size:0.68rem;padding:3px 9px;border-radius:20px;font-weight:600;">
                                    ${act.market_value} Value</span>` : ''}
                            </div>
                            <p class="feed-bullet mb-2">
                                <span class="bullet-short">${shortText}</span>
                                ${isLong ? `<span class="bullet-full d-none">${snippet}</span>` : ''}
                            </p>
                            ${isLong ? `<button class="feed-expand-btn mb-2" onclick="toggleBullet(this)" aria-expanded="false">Show more <i class="bi bi-chevron-down"></i></button>` : ''}
                            ${skillsHtml ? `<div class="feed-badges">${skillsHtml}</div>` : ''}
                        `;
                        df.appendChild(div);
                    });
                    if (feedContainer) feedContainer.appendChild(df);

                    const count = feedContainer ? feedContainer.querySelectorAll('.feed-card').length : 0;
                    if (feedCountEl && count > 0) {
                        feedCountEl.textContent = count + ' bullet' + (count !== 1 ? 's' : '');
                        feedCountEl.classList.remove('d-none');
                    }
                }
            }
        })
        .catch(err => console.error("Error fetching initial metrics:", err));

    // PDF Export
    if (downloadPdfBtn) {
        downloadPdfBtn.addEventListener('click', function () {
            window.location.href = `/generate_pdf?csrf_token=${encodeURIComponent(csrfToken)}`;
        });
    }
});

// ── Global helpers (outside DOMContentLoaded so onclick= attributes can call them) ──

/** Toggle Show more / Show less on a feed bullet */
function toggleBullet(btn) {
    const card    = btn.closest('.feed-card');
    const short   = card?.querySelector('.bullet-short');
    const full    = card?.querySelector('.bullet-full');
    const isOpen  = btn.getAttribute('aria-expanded') === 'true';
    if (!short || !full) return;
    short.classList.toggle('d-none', !isOpen);
    full.classList.toggle('d-none', isOpen);
    btn.setAttribute('aria-expanded', String(!isOpen));
    btn.innerHTML = isOpen
        ? 'Show more <i class="bi bi-chevron-down" aria-hidden="true"></i>'
        : 'Show less <i class="bi bi-chevron-up" aria-hidden="true"></i>';
}

/** Animate the multi-step loading progress bar during analysis */
function animateProgressSteps() {
    const steps = ['ps-nlp','ps-gemini','ps-match','ps-dash'];
    const delays = [0, 800, 1800, 2600];
    steps.forEach((id, i) => {
        setTimeout(() => {
            const el = document.getElementById(id);
            if (!el) return;
            el.classList.add('active');
            el.querySelector('.step-spinner')?.replaceWith((() => {
                const s = document.createElement('span');
                s.className = 'step-spinner';
                return s;
            })());
        }, delays[i]);
    });
}