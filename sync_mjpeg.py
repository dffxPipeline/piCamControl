#!/usr/bin/env python3
import argparse
import numpy as np
import cv2
import os


def resync_video_with_pts(mjpeg_path, pts_path, output_path, master_pts, target_fps=24, debug=False):
    # Load PTS and normalize to start at 0
    pts = np.loadtxt(pts_path)
    pts -= pts[0]

    # Normalize master_pts to start at 0
    master_pts = master_pts - master_pts[0]

    # Open MJPEG video
    cap = cv2.VideoCapture(mjpeg_path)
    if debug:
        print(f"[DEBUG] Opened video: {mjpeg_path}")

    # Read all frames into memory using robust loop
    frames = []
    frame_index = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            if debug:
                print(f"[DEBUG] End of video stream at frame {frame_index}")
            break
        frames.append(frame)
        frame_index += 1
        if debug and frame_index % 50 == 0:
            print(f"[DEBUG] Read frame {frame_index}")
    cap.release()

    if not frames:
        raise RuntimeError("No frames read from input video.")

    # Find closest matching frame indices to master timeline
    indices = np.searchsorted(pts, master_pts)
    indices = np.clip(indices, 0, len(frames) - 1)

    # Write out new synced video
    height, width = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, target_fps, (width, height))

    for i, idx in enumerate(indices):
        out.write(frames[idx])
        if debug and i % 50 == 0:
            print(f"[DEBUG] Writing frame {i} using source frame {idx}")
    out.release()

    print(f"[✓] Synced video saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Resync MJPEG video using PTS to match master timeline")
    parser.add_argument('--mjpeg', required=True, help="Path to input MJPEG video")
    parser.add_argument('--pts', required=True, help="Path to input PTS file (microseconds per frame)")
    parser.add_argument('--master', required=True, help="Path to master camera PTS file")
    parser.add_argument('--output', required=True, help="Path to output synced video (MP4 format)")
    parser.add_argument('--fps', type=int, default=24, help="Target framerate for output video")
    parser.add_argument('--debug', action='store_true', help="Enable debug output")
    args = parser.parse_args()

    if not os.path.exists(args.mjpeg):
        raise FileNotFoundError(f"Missing MJPEG file: {args.mjpeg}")
    if not os.path.exists(args.pts):
        raise FileNotFoundError(f"Missing PTS file: {args.pts}")
    if not os.path.exists(args.master):
        raise FileNotFoundError(f"Missing master PTS file: {args.master}")

    master_pts = np.loadtxt(args.master)
    resync_video_with_pts(
        mjpeg_path=args.mjpeg,
        pts_path=args.pts,
        output_path=args.output,
        master_pts=master_pts,
        target_fps=args.fps,
        debug=args.debug
    )


if __name__ == "__main__":
    main()
