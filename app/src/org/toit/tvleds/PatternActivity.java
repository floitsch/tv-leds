// Copyright (C) 2026 Toit contributors.
package org.toit.tvleds;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;

/** Known colors and motion for validating capture independently of video apps. */
public final class PatternActivity extends Activity {
    private String mode;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        show(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        show(intent);
    }

    private void show(Intent intent) {
        mode = intent.getStringExtra("mode");
        if (mode == null) mode = "bars";
        final Bitmap reference = mode.equals("reference-image")
            ? BitmapFactory.decodeFile(new java.io.File(getFilesDir(), "reference.jpg").getPath())
            : null;
        if (mode.equals("reference-image") && reference == null) {
            throw new IllegalArgumentException("Upload files/reference.jpg before selecting reference-image");
        }
        if (intent.getBooleanExtra("secure", false)) getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().getDecorView().setSystemUiVisibility(5894);
        setContentView(new View(this) {
            private final Paint paint = new Paint();
            @Override protected void onDraw(Canvas canvas) {
                int width = getWidth(), height = getHeight();
                if (reference != null) canvas.drawBitmap(reference, null, new Rect(0, 0, width, height), paint);
                else if (mode.equals("red")) canvas.drawColor(Color.RED);
                else if (mode.equals("green")) canvas.drawColor(Color.GREEN);
                else if (mode.equals("blue")) canvas.drawColor(Color.BLUE);
                else if (mode.equals("black")) canvas.drawColor(Color.BLACK);
                else if (mode.equals("white")) canvas.drawColor(Color.WHITE);
                else if (mode.equals("letterbox") || mode.equals("letterbox-osd")) {
                    canvas.drawColor(Color.BLACK);
                    paint.setColor(Color.GREEN);
                    canvas.drawRect(0, height / 8f, width, height * 7 / 8f, paint);
                    if (mode.equals("letterbox-osd")) {
                        paint.setColor(Color.WHITE);
                        canvas.drawRect(width * 3 / 8f, height * 15 / 16f,
                            width * 5 / 8f, height * 31 / 32f, paint);
                    }
                }
                else if (mode.equals("pillarbox")) {
                    canvas.drawColor(Color.BLACK);
                    paint.setColor(Color.MAGENTA);
                    canvas.drawRect(width / 8f, 0, width * 7 / 8f, height, paint);
                }
                else if (mode.equals("windowbox")) {
                    canvas.drawColor(Color.BLACK);
                    paint.setColor(Color.CYAN);
                    canvas.drawRect(width / 8f, height / 8f, width * 7 / 8f, height * 7 / 8f, paint);
                }
                else if (mode.equals("fullframe-edges")) {
                    canvas.drawColor(Color.RED);
                    paint.setColor(Color.GREEN);
                    canvas.drawRect(width / 8f, height / 8f, width * 7 / 8f, height * 7 / 8f, paint);
                }
                else if (mode.equals("middle-band")) {
                    canvas.drawColor(Color.BLACK);
                    paint.setColor(Color.GREEN);
                    canvas.drawRect(0, height / 4f, width, height * 3 / 4f, paint);
                }
                else if (mode.equals("moving-band")) {
                    canvas.drawColor(Color.BLACK);
                    float phase = (android.os.SystemClock.uptimeMillis() % 8000) / 4000f;
                    float position = phase <= 1 ? phase : 2 - phase;
                    float top = position * height * 3 / 4f;
                    paint.setColor(Color.GREEN);
                    canvas.drawRect(0, top, width, top + height / 4f, paint);
                    postInvalidateOnAnimation();
                }
                else if (mode.equals("horizontal-colors")) {
                    canvas.drawColor(Color.BLACK);
                    paint.setColor(Color.RED);
                    canvas.drawRect(0, height / 8f, width, height / 4f, paint);
                    paint.setColor(Color.GREEN);
                    canvas.drawRect(0, height / 4f, width, height / 2f, paint);
                    paint.setColor(Color.BLUE);
                    canvas.drawRect(0, height / 2f, width, height * 3 / 4f, paint);
                }
                else {
                    int[] colors = {Color.RED, Color.GREEN, Color.BLUE, Color.WHITE};
                    for (int i = 0; i < 4; i++) {
                        paint.setColor(colors[i]);
                        canvas.drawRect(i * width / 4f, 0, (i + 1) * width / 4f, height, paint);
                    }
                    if (mode.equals("moving")) {
                        float x = (android.os.SystemClock.uptimeMillis() % 3000) * width / 3000f;
                        paint.setColor(Color.BLACK);
                        canvas.drawRect(x, height / 3f, x + width / 8f, height * 2 / 3f, paint);
                        postInvalidateOnAnimation();
                    }
                }
            }
        });
    }
}
