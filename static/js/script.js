// YouTube Downloader Frontend Script

document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const youtubeUrlInput = document.getElementById('youtube-url');
    const fetchInfoBtn = document.getElementById('fetch-info-btn');
    const videoInfoCard = document.getElementById('video-info-card');
    const videoTitle = document.getElementById('video-title');
    const videoUploader = document.getElementById('video-uploader');
    const videoDuration = document.getElementById('video-duration');
    const videoViews = document.getElementById('video-views');
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
    const newDownloadBtnError = document.getElementById('new-download-btn-error');

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
        
        // Clear existing options except the first one
        while (qualitySelect.options.length > 1) {
            qualitySelect.remove(1);
        }
        
        if (!currentVideoInfo) return;
        
        if (format === 'video') {
            // Show quality container for videos
            qualityContainer.classList.remove('d-none');
            
            // Add video format options
            currentVideoInfo.formats.forEach(format => {
                if (format.resolution !== 'audio_only') {
                    const option = document.createElement('option');
                    option.value = format.resolution;
                    option.textContent = `${format.resolution}${format.fps ? ' @ ' + format.fps + 'fps' : ''}`;
                    qualitySelect.appendChild(option);
                }
            });
        } else if (format === 'audio') {
            // Hide quality container for audio
            qualityContainer.classList.add('d-none');
        } else if (format === 'thumbnail') {
            // Hide quality container for thumbnails
            qualityContainer.classList.add('d-none');
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
            videoDuration.textContent = formatDuration(data.duration);
            videoViews.textContent = formatViewCount(data.view_count);
            
            // Set thumbnail if available
            if (data.thumbnails && data.thumbnails.length > 0) {
                thumbnailContainer.innerHTML = '';
                thumbnailContainer.style.backgroundImage = `url('${data.thumbnails[0].url}')`;
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
        
        // Clear any existing intervals
        if (progressInterval) {
            clearInterval(progressInterval);
        }
        
        // Check progress every 500ms
        progressInterval = setInterval(() => {
            fetch(`/api/progress/${currentDownloadId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Failed to get progress');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.error) {
                        throw new Error(data.error);
                    }
                    
                    // Update progress bar
                    const progress = Math.round(data.progress);
                    progressBar.style.width = `${progress}%`;
                    progressBar.textContent = `${progress}%`;
                    
                    // Update speed and ETA
                    if (data.speed && data.speed !== 'N/A') {
                        downloadSpeed.textContent = `Speed: ${data.speed}`;
                    }
                    
                    if (data.eta && data.eta !== 'N/A') {
                        downloadEta.textContent = `ETA: ${data.eta}`;
                    }
                    
                    // Check if download is complete or failed
                    if (data.status === 'completed') {
                        clearInterval(progressInterval);
                        downloadComplete();
                    } else if (data.status === 'failed') {
                        clearInterval(progressInterval);
                        showDownloadError('Download failed');
                    } else if (data.status === 'canceled') {
                        clearInterval(progressInterval);
                        showDownloadError('Download was canceled');
                    }
                })
                .catch(error => {
                    console.error('Error tracking progress:', error);
                    clearInterval(progressInterval);
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
