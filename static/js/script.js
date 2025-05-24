// YouTube Downloader Frontend Script

document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const youtubeUrlInput = document.getElementById('youtube-url');
    const fetchInfoBtn = document.getElementById('fetch-info-btn');
    const videoInfoCard = document.getElementById('video-info-card');
    const videoTitle = document.getElementById('video-title');
    const videoUploader = document.getElementById('video-uploader');
    const videoViews = document.getElementById('video-views');
    const videoLikes = document.getElementById('video-likes');
    const channelSubscribers = document.getElementById('channel-subscribers');
    const thumbnailContainer = document.getElementById('thumbnail-container');
    const formatSelect = document.getElementById('format-select');
    const qualityContainer = document.getElementById('quality-container');
    const qualitySelect = document.getElementById('quality-select');
    const downloadBtn = document.getElementById('download-btn');
    const downloadProgressCard = document.getElementById('download-progress-card');
    const progressBar = document.getElementById('progress-bar');
    const downloadSpeed = document.getElementById('download-speed');
    const downloadEta = document.getElementById('download-eta');
    const cancelBtn = document.getElementById('cancel-btn');
    const downloadCompleteContainer = document.getElementById('download-complete-container');
    const downloadLink = document.getElementById('download-link');
    const newDownloadBtn = document.getElementById('new-download-btn');
    const downloadErrorContainer = document.getElementById('download-error-container');
    const errorMessage = document.getElementById('error-message');
    const retryBtn = document.getElementById('retry-btn');
    const bestQualityInfo = document.getElementById('best-quality-info');
    const newDownloadBtnError = document.getElementById('new-download-btn-error');
    const channelLogo = document.getElementById('channel-logo');

    // State
    let currentVideoInfo = null;
    let currentDownloadId = null;
    let progressInterval = null;
    
    // Format duration from seconds to MM:SS or HH:MM:SS
    function formatDuration(seconds) {
        if (!seconds) return '0:00';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        } else {
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }
    }
    
    // Format view count with commas
    function formatViewCount(count) {
        if (!count) return '0 views';
        return `${count.toLocaleString()} views`;
    }
    
    // Reset the UI to initial state
    function resetUI() {
        youtubeUrlInput.value = '';
        videoInfoCard.classList.add('d-none');
        downloadProgressCard.classList.add('d-none');
        downloadCompleteContainer.classList.add('d-none');
        downloadErrorContainer.classList.add('d-none');
        thumbnailContainer.style.backgroundImage = '';
        thumbnailContainer.innerHTML = '<i class="bi bi-image text-secondary" style="font-size: 3rem;"></i>';
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
        
        // Clear intervals
        if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
        }
        
        currentVideoInfo = null;
        currentDownloadId = null;
    }
    
    // Update the quality select based on format
    function updateQualityOptions() {
        const format = formatSelect.value;
        
        // Helper to map resolutions to labels
        function friendlyResolution(res) {
            switch (res) {
                case '3840x2160': return '4K';
                case '2560x1440': return '2K';
                case '1920x1080': return '1K';
                case '1280x720': return '720';
                default: return res;
            }
        }
        
        // Clear all existing options
        qualitySelect.innerHTML = '';
        
        if (format === 'video' && currentVideoInfo) {
            qualityContainer.classList.remove('d-none');
            currentVideoInfo.formats.forEach(fmt => {
                if (fmt.resolution !== 'audio_only' && /^\d+x\d+$/.test(fmt.resolution)) {
                    const option = document.createElement('option');
                    option.value = fmt.resolution;
                    const label = friendlyResolution(fmt.resolution);
                    option.textContent = `${label}${fmt.fps ? ' ' + fmt.fps + 'fps' : ''}`;
                    qualitySelect.appendChild(option);
                }
            });
            // Default to 1K (1080p) if available
            if (qualitySelect.querySelector('option[value="1920x1080"]')) {
                qualitySelect.value = '1920x1080';
            } else {
                qualitySelect.selectedIndex = 0;
            }
            // Show dynamic best-quality info based on available resolutions
            const heights = currentVideoInfo.formats
                .map(fmt => fmt.resolution)
                .filter(r => /^\d+x\d+$/.test(r))
                .map(r => parseInt(r.split('x')[1], 10));
            const maxHeight = heights.length ? Math.max(...heights) : 0;
            // Map maxHeight to friendly quality text
            let bestQualityText;
            if (maxHeight >= 2160) {
                bestQualityText = '4K';
            } else if (maxHeight >= 1440) {
                bestQualityText = '2K';
            } else if (maxHeight >= 1080) {
                bestQualityText = '1080p';
            } else if (maxHeight >= 720) {
                bestQualityText = '720p';
            } else {
                bestQualityText = `${maxHeight}p`;
            }
            if (bestQualityInfo) {
                bestQualityInfo.textContent = `The best video quality available for this video is ${bestQualityText}.`;
            }
        } else {
            qualityContainer.classList.add('d-none');
            if (bestQualityInfo) {
                bestQualityInfo.textContent = '';
            }
        }
    }
    
    // Fetch video information
    function fetchVideoInfo(url) {
        // Basic URL validation
        if (!url.match(/^(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)) {
            alert('Please enter a valid YouTube URL');
            return;
        }
        
        // Change button to loading state
        fetchInfoBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
        fetchInfoBtn.disabled = true;
        
        fetch('/api/video-info', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch video information');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Store video info
            currentVideoInfo = data;
            
            // Update UI
            videoTitle.textContent = data.title || 'Unknown Title';
            videoUploader.textContent = data.uploader || 'Unknown Uploader';
            videoViews.textContent = formatViewCount(data.view_count);
            
            // Format and update likes count
            const likesCount = data.like_count || 0;
            if (videoLikes) {
                let likesText = '';
                if (likesCount >= 1000000) {
                    const floored = Math.floor(likesCount / 100000) / 10;
                    likesText = `${floored}M likes`;
                } else if (likesCount >= 1000) {
                    const floored = Math.floor(likesCount / 100) / 10;
                    likesText = `${floored}K likes`;
                } else {
                    likesText = `${likesCount} likes`;
                }
                videoLikes.textContent = likesText;
            }
            
            // Format and update subscriber count
            if (channelSubscribers) {
                if (data.subscriber_count && data.subscriber_count !== 'N/A') {
                    let subCount = data.subscriber_count;
                    let displaySubs;
                    if (subCount >= 1000000) {
                        displaySubs = `${(subCount / 1000000).toFixed(1)}M subscribers`;
                    } else if (subCount >= 1000) {
                        displaySubs = `${(subCount / 1000).toFixed(1)}K subscribers`;
                    } else {
                        displaySubs = `${subCount} subscribers`;
                    }
                    channelSubscribers.textContent = displaySubs;
                } else {
                    channelSubscribers.textContent = 'Subscribers unavailable';
                }
            }
            
            // Update channel logo if available
            if (data.channel_logo) {
                channelLogo.src = data.channel_logo;
                channelLogo.style.display = 'inline-block';
            } else {
                channelLogo.style.display = 'none';
            }
            
            // Set thumbnail and duration badge if available
            if (data.thumbnails && data.thumbnails.length > 0) {
                // Duration badge overlay
                const badge = document.createElement('div');
                badge.className = 'duration-badge';
                badge.textContent = formatDuration(data.duration);
                // Clear container and set background
                thumbnailContainer.innerHTML = '';
                thumbnailContainer.style.backgroundImage = `url('${data.thumbnails[0].url}')`;
                thumbnailContainer.appendChild(badge);
            }
            
            // Update quality options
            updateQualityOptions();
            
            // Show video info card
            videoInfoCard.classList.remove('d-none');
        })
        .catch(error => {
            alert('Error: ' + error.message);
            console.error('Error:', error);
        })
        .finally(() => {
            // Reset button state
            fetchInfoBtn.innerHTML = '<i class="bi bi-search"></i> Fetch Info';
            fetchInfoBtn.disabled = false;
        });
    }
    
    // Start the download process
    function startDownload() {
        if (!currentVideoInfo) return;
        
        const url = youtubeUrlInput.value;
        const format = formatSelect.value;
        const quality = format === 'video' ? qualitySelect.value : 'best';
        
        // Hide video info and show progress
        videoInfoCard.classList.add('d-none');
        downloadProgressCard.classList.remove('d-none');
        downloadCompleteContainer.classList.add('d-none');
        downloadErrorContainer.classList.add('d-none');
        
        // Reset progress
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
        downloadSpeed.textContent = 'Speed: Calculating...';
        downloadEta.textContent = 'ETA: Calculating...';
        
        // Send download request
        fetch('/api/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url, format, quality })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to start download');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Store download ID
            currentDownloadId = data.download_id;
            
            // Start progress tracking
            trackDownloadProgress();
        })
        .catch(error => {
            console.error('Error starting download:', error);
            showDownloadError(error.message);
        });
    }
    
    // Track download progress
    function trackDownloadProgress() {
        if (!currentDownloadId) return;
        if (progressInterval) clearInterval(progressInterval);
        let smoothProgress = 0;
        let smoothingInterval = null;
        progressInterval = setInterval(() => {
            fetch(`/api/progress/${currentDownloadId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) throw new Error(data.error);
                    let targetProgress = Math.round(data.progress);
                    // Smooth progress bar
                    if (targetProgress > smoothProgress) {
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        smoothingInterval = setInterval(() => {
                            if (smoothProgress < targetProgress) {
                                smoothProgress++;
                                progressBar.style.width = `${smoothProgress}%`;
                                progressBar.textContent = `${smoothProgress}%`;
                            } else {
                                clearInterval(smoothingInterval);
                            }
                        }, 20);
                    } else {
                        progressBar.style.width = `${targetProgress}%`;
                        progressBar.textContent = `${targetProgress}%`;
                        smoothProgress = targetProgress;
                    }
                    // Show speed
                    if (data.speed && data.speed !== 'N/A') {
                        downloadSpeed.textContent = `Speed: ${data.speed}`;
                    }
                    // ETA logic
                    if (data.eta && data.eta !== 'N/A' && data.eta !== '00:00' && data.eta !== 'Processing...') {
                        downloadEta.textContent = `ETA: ${data.eta}`;
                    } else if (data.status === 'processing') {
                        downloadEta.textContent = `ETA: Processing...`;
                    } else if (data.progress > 0 && data.progress < 100 && data.elapsed) {
                        const secondsRemaining = Math.round((data.elapsed / data.progress) * (100 - data.progress));
                        downloadEta.textContent = `ETA: ${formatDuration(secondsRemaining)}`;
                    } else {
                        downloadEta.textContent = `ETA: Calculating...`;
                    }
                    // Handle completion/failure
                    if (data.status === 'completed') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        progressBar.style.width = `100%`;
                        progressBar.textContent = `100%`;
                        downloadComplete();
                    } else if (data.status === 'failed') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        showDownloadError('Download failed');
                    } else if (data.status === 'canceled') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        showDownloadError('Download was canceled');
                    }
                })
                .catch(error => {
                    clearInterval(progressInterval);
                    if (smoothingInterval) clearInterval(smoothingInterval);
                    showDownloadError(error.message);
                });
        }, 500);
    }
    
    // Handle download completion
    function downloadComplete() {
        // Hide cancel button
        cancelBtn.classList.add('d-none');
        
        // Update link and show download complete UI
        downloadLink.href = `/api/download-file/${currentDownloadId}`;
        downloadCompleteContainer.classList.remove('d-none');
        // Automatically trigger download
        downloadLink.click();
    }
    
    // Show download error
    function showDownloadError(message) {
        downloadErrorContainer.classList.remove('d-none');
        errorMessage.textContent = message || 'An unknown error occurred';
        cancelBtn.classList.add('d-none');
    }
    
    // Cancel the current download
    function cancelDownload() {
        if (!currentDownloadId) return;
        
        fetch(`/api/cancel/${currentDownloadId}`, {
            method: 'POST'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to cancel download');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Clear progress interval
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            
            showDownloadError('Download canceled');
        })
        .catch(error => {
            console.error('Error canceling download:', error);
        });
    }
    
    // Event Listeners
    fetchInfoBtn.addEventListener('click', () => {
        fetchVideoInfo(youtubeUrlInput.value);
    });
    
    youtubeUrlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            fetchVideoInfo(youtubeUrlInput.value);
        }
    });
    
    formatSelect.addEventListener('change', updateQualityOptions);
    
    downloadBtn.addEventListener('click', startDownload);
    
    cancelBtn.addEventListener('click', cancelDownload);
    
    newDownloadBtn.addEventListener('click', resetUI);
    
    newDownloadBtnError.addEventListener('click', resetUI);
    
    retryBtn.addEventListener('click', () => {
        // Hide error UI and go back to video info
        downloadErrorContainer.classList.add('d-none');
        videoInfoCard.classList.remove('d-none');
        downloadProgressCard.classList.add('d-none');
        cancelBtn.classList.remove('d-none');
    });
});
