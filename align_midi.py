# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

# <codecell>

import numpy as np
import librosa
import scipy.stats
import scipy.spatial.distance
import matplotlib.pyplot as plt

# <codecell>

def dpmod(M, pen=1.0, G=0.0):
    '''
    Use dynamic programming to find a min-cost path through matrix M.
    
    Input:
        M - Matrix to find path through
        pen - cost scale for for (0,1) and (1,0) steps (default 1.0)
        G - acceptable "gullies" (0..1, default 0)
    Output:
        p, q - State sequence
        D - Cost matrix
        phi - Backtrace
        score - DP score
    '''
    
    side_fill_value = 2*M.max()
    
    # Matrix of costs, with an additional row and column at the beginning and end
    D = np.zeros(M.shape)
    # Compute size of gulley in rows and columns
    gulley_x = int(round(G*M.shape[1]))
    gulley_y = int(round(G*M.shape[0]))
    # Must be at least 1 for the logic below to work
    gulley_x += (gulley_x == 0)
    gulley_y += (gulley_y == 0)
    # Fill in a linear ramp of length gulley_x in the first row to M.max()
    D[0, :gulley_x] += np.linspace(0, side_fill_value, gulley_x)
    # Same for first column
    D[:gulley_y, 0] += np.linspace(0, side_fill_value, gulley_y)
    # Now, ramp from M.max() to 0 for the bottom right corner
    D[-1, -gulley_x:] += np.linspace(0, side_fill_value, gulley_x)[::-1]
    D[-gulley_y:, -1] += np.linspace(0, side_fill_value, gulley_y)[::-1]
    # After the ramp, just fill in the max til the end
    D[0, gulley_x:] += side_fill_value    
    D[gulley_y:, 0] += side_fill_value    
    D[-1, :-gulley_x] += side_fill_value
    D[:-gulley_y, -1] += side_fill_value  
    # Finally, populate the middle of the matrix with the local costs
    D += M
    
    # Store the traceback
    phi = np.zeros(D.shape)
    # Handle first row/column, where we force back to the beginning
    D[0, :] = np.cumsum(D[0, :])
    D[:, 0] = np.cumsum(D[:, 0])
    phi[0, :] = 2
    phi[:, 0] = 1
    phi[0, 0] = 0   
    # Handle final row/column, where we force starting at bottom right corner
    #D[-1, ::-1] = np.cumsum(D[-1, ::-1])    
    #D[::-1, -1] = np.cumsum(D[::-1, -1])
    
    for i in xrange(D.shape[0] - 1): 
        for j in xrange(D.shape[1] - 1):
            # The possible locations we can move to, weighted by penalty score
            next_moves = [D[i, j], pen*D[i, j + 1], pen*D[i + 1, j]]
            # Choose the lowest cost
            tb = np.argmin(next_moves)
            dmin = next_moves[tb]
            # Add in the cost
            D[i + 1, j + 1] = D[i + 1, j + 1] + dmin
            # Store the traceback
            phi[i + 1, j + 1] = tb
    
        
    # Traceback from corner
    i = np.argmin(D[:, -1])
    j = np.argmin(D[-1, :])
    if D[i, -1] < D[-1, j]:
        j = D.shape[1] - 1
    else:
        i = D.shape[0] - 1
    
    # Score is the final score of the best path
    score = D[i, j]
    
    # These vectors will give the lowest-cost path
    p = np.array([i])
    q = np.array([j])
    
    # Until we reach an edge
    while i > 0 or j > 0:
        # If the tracback matrix indicates a diagonal move...
        if phi[i, j] == 0:
            i = i - 1
            j = j - 1
        # Horizontal move...
        elif phi[i, j] == 1:
            i = i - 1
        # Vertical move...
        elif phi[i, j] == 2:
            j = j - 1
        # Add these indices into the path arrays
        p = np.append(i, p)
        q = np.append(j, q)
        
    # Normalize score
    score = score/q.shape[0]
    
    return p, q, D, phi, score

# <codecell>

def maptimes(t, intime, outtime):
    '''
    map the times in t according to the mapping that each point in intime corresponds to that value in outtime
    2008-03-20 Dan Ellis dpwe@ee.columbia.edu
    
    Input:
        t - list of times to map
        intimes - original times
        outtime - mapped time
    Output:
        u - mapped version of t
    '''

    # Make sure both time ranges start at or before zero
    pregap = max(intime[0], outtime[0])
    intime = np.append(intime[0] - pregap, intime)
    outtime = np.append(outtime[0] - pregap, outtime)
    
    # Make sure there's a point beyond the end of both sequences
    din = np.diff(np.append(intime, intime[-1] + 1))
    dout = np.diff(np.append(outtime, outtime[-1] + 1))
    
    # Decidedly faster than outer-product-array way
    u = np.array(t)
    for i in xrange(t.shape[0]):
      ix = -1 + np.min(np.append(np.flatnonzero(intime > t[i]), outtime.shape[0]))
      # offset from that time
      dt = t[i] - intime[ix];
      # perform linear interpolation
      u[i] = outtime[ix] + (dt/din[ix])*dout[ix]
    return u

# <codecell>

def align_midi(midi, midi_audio, audio, fs):
    '''
    Aligns a PrettyMidi object to some audio data
    
    Input:
        midi - pretty_midi.PrettyMIDI object
        midi_audio - synthesis of the midi object
        audio - audio data which should be the same song as midi
        fs - Sampling rate of audio data
    Output:
        midi_aligned - midi aligned to audio, another pretty_midi.PrettyMIDI object
        cost - DP cost
    '''
    # Compute log frequency spectrogram of audio synthesized from MIDI
    midi_gram = np.abs(librosa.cqt(y=midi_audio,
                                   sr=fs,
                                   hop_length=512,
                                   fmin=librosa.midi_to_hz(36),
                                   n_bins=60,
                                   tuning=0.0))**2
    # Estimate MIDI beat times
    midi_beats = np.array(midi.get_beats()*fs/512.0, dtype=np.int)
    # Estimate the MIDI tempo
    midi_tempo = 60.0/np.mean(np.diff(midi.get_beats()))
    # Make tempo faster for better temporal resolution
    scale = 1
    while midi_tempo < 240:
        midi_tempo *= 2
        scale *= 2
    # Interpolate the beats to match the higher tempo
    midi_beats = np.array(np.interp(np.linspace(0, scale*(midi_beats.shape[0] - 1), scale*(midi_beats.shape[0] - 1) + 1),
                                    np.linspace(0, scale*(midi_beats.shape[0] - 1), midi_beats.shape[0]),
                                    midi_beats), dtype=np.int)
    # Truncate to length of audio
    midi_beats = midi_beats[midi_beats < midi_gram.shape[1]]
    # Synchronize the log-fs gram with MIDI beats
    midi_gram = librosa.feature.sync(midi_gram, midi_beats)[:, 1:]
    # Compute log-amplitude spectrogram
    midi_gram = librosa.logamplitude(midi_gram, ref_power=midi_gram.max())
    
    # Use harmonic part for gram, percussive part for beats
    H, P = librosa.decompose.hpss(librosa.stft(audio))
    audio_harmonic = librosa.istft(H)
    audio_percussive = librosa.istft(P)
    # Compute log-frequency spectrogram of original audio
    audio_gram = np.abs(librosa.cqt(y=audio_harmonic,
                                    sr=fs,
                                    hop_length=512,
                                    fmin=librosa.midi_to_hz(36),
                                    n_bins=60))**2
    # Beat track the audio file
    audio_beats = librosa.beat.beat_track(audio_percussive, hop_length=128, bpm=midi_tempo)[1]/4
    # Synchronize the log frequency spectrogram to the beat times
    audio_gram = librosa.feature.sync(audio_gram, audio_beats)[:, 1:]
    # Compute log-amplitude spectrogram
    audio_gram = librosa.logamplitude(audio_gram, ref_power=audio_gram.max())
    
    # Plot log-fs grams
    plt.figure(figsize=(24, 24))
    ax = plt.subplot2grid((4, 2), (0, 0), colspan=2)
    plt.title('MIDI Synthesized')
    librosa.display.specshow(midi_gram,
                             x_axis='frames',
                             y_axis='cqt_note',
                             fmin=librosa.midi_to_hz(36),
                             fmax=librosa.midi_to_hz(96))
    ax = plt.subplot2grid((4, 2), (1, 0), colspan=2)
    plt.title('Audio data')
    librosa.display.specshow(audio_gram,
                             x_axis='frames',
                             y_axis='cqt_note',
                             fmin=librosa.midi_to_hz(36),
                             fmax=librosa.midi_to_hz(96))

    # Normalize the columns
    midi_gram_normalized = librosa.util.normalize(midi_gram, axis=0)
    audio_gram_normalized = librosa.util.normalize(audio_gram, axis=0)

    # Get similarity matrix
    similarity_matrix = scipy.spatial.distance.cdist(midi_gram_normalized.T, audio_gram_normalized.T, metric='seuclidean')
    
    # Get best path through matrix
    p, q, D, phi, score = dpmod(similarity_matrix**2, 1.01, 0.)
    # Plot similarity matrix and best path through it
    ax = plt.subplot2grid((4, 2), (2, 0), rowspan=2)
    plt.imshow(similarity_matrix.T,
               aspect='auto',
               interpolation='nearest',
               cmap=plt.cm.gray)
    tight = plt.axis()
    plt.plot(p, q, 'r.', ms=.2)
    plt.axis(tight)
    plt.title('Similarity matrix and lowest-cost path, cost={}'.format(score))
    
    # Get aligned beat location arrays
    midi_beats_aligned = librosa.frames_to_time(midi_beats)[p]
    audio_beats_aligned = librosa.frames_to_time(audio_beats)[q]
    # Get array of note-on locations and correct them
    note_ons = np.array([note.start for instrument in midi.instruments for note in instrument.events])
    aligned_note_ons = maptimes(note_ons, midi_beats_aligned, audio_beats_aligned)
    # Same for note-offs
    note_offs = np.array([note.end for instrument in midi.instruments for note in instrument.events])
    aligned_note_offs = maptimes(note_offs, midi_beats_aligned, audio_beats_aligned)
    # Same for pitch bends
    pitch_bends = np.array([bend.time for instrument in midi.instruments for bend in instrument.pitch_bends])
    aligned_pitch_bends = maptimes(pitch_bends, midi_beats_aligned, audio_beats_aligned)
    
    # Correct notes
    for n, note in enumerate([note for instrument in midi.instruments for note in instrument.events]):
        note.start = (aligned_note_ons[n] > 0)*aligned_note_ons[n]
        note.end = (aligned_note_offs[n] > 0)*aligned_note_offs[n]
    # Correct pitch changes
    for n, bend in enumerate([bend for instrument in midi.instruments for bend in instrument.pitch_bends]):
        bend.time = (aligned_pitch_bends[n] > 0)*aligned_pitch_bends[n]

    # Plot alignment
    ax = plt.subplot2grid((4, 2), (2, 1), rowspan=2)
    plt.plot(note_ons, aligned_note_ons - note_ons, '.')
    plt.xlabel('Original note location (s)')
    plt.ylabel('Shift (s)')
    plt.title('Corrected offset')
    
    return midi

# <codecell>

if __name__ == '__main__':
    import midi
    import pretty_midi
    import glob
    import subprocess
    import joblib
    import os
    SF2_PATH = '../Performer Synchronization Measure/SGM-V2.01.sf2'
    OUTPUT_PATH = 'midi-aligned-new-new-dpmod'
    if not os.path.exists(os.path.join('data/cal500/', OUTPUT_PATH)):
        os.makedirs(os.path.join('data/cal500/', OUTPUT_PATH))
    
    def process_one_file(filename):
        '''
        Helper function for aligning a single audio file.
        '''
        # Load in the corresponding midi file in the midi directory
        try:
            m = pretty_midi.PrettyMIDI(midi.read_midifile(filename.replace('audio', 'midi').replace('.mp3', '.mid')))
        except:
            return
        print filename.split('/')[-1]
        # Load in audio data
        audio, fs = librosa.load(filename)
        midi_audio, fs = librosa.load(filename.replace('audio', 'midi'), sr=fs)
        # Perform the alignment
        m = align_midi(m, midi_audio, audio, fs)
        # Write out the aligned file
        m.write(filename.replace('audio', OUTPUT_PATH).replace('.mp3', '.mid'))
        # Synthesize the aligned midi
        m_aligned = m.synthesize(fs=fs, method=SF2_PATH)
        # Trim to the same size as audio
        if m_aligned.shape[0] > audio.shape[0]:
            m_aligned = m_aligned[:audio.shape[0]]
        else:
            m_aligned = np.pad(m_aligned, (0, audio.shape[0] - m_aligned.shape[0]), 'constant')
        # Write out
        librosa.output.write_wav(filename.replace('audio', OUTPUT_PATH).replace('.mp3', '.wav'),
                                 np.vstack([m_aligned, audio]).T, fs)
        # Convert to mp3
        subprocess.call(['ffmpeg',
                         '-i',
                         filename.replace('audio', OUTPUT_PATH).replace('.mp3', '.wav'),
                         '-ab',
                         '128k',
                         '-y',
                         filename.replace('audio', OUTPUT_PATH)])
        os.remove(filename.replace('audio', OUTPUT_PATH).replace('.mp3', '.wav'))
        plt.savefig(filename.replace('audio', OUTPUT_PATH).replace('.mp3', '.pdf'))
        plt.close()
    
    # Parallelization!
    joblib.Parallel(n_jobs=6)(joblib.delayed(process_one_file)(filename) for filename in glob.glob('data/cal500/audio/*.mp3'))

