/* SPDX-License-Identifier: GPL-3.0-or-later
 * Madeira Converter Exception: see LICENSE-EXCEPTION.md.
 * Hidden-window OpenGL 3.3 canary. Run inside Wine to validate the Metal path;
 * a Windows-host pass validates Mesa/WGL only, not iDeck's D3D12 renderer. */
#include <windows.h>
#include <stddef.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GL_VERTEX_SHADER 0x8b31
#define GL_FRAGMENT_SHADER 0x8b30
#define GL_COMPILE_STATUS 0x8b81
#define GL_LINK_STATUS 0x8b82
#define GL_FRAMEBUFFER 0x8d40
#define GL_FRAMEBUFFER_COMPLETE 0x8cd5
#define GL_COLOR_ATTACHMENT0 0x8ce0
#define GL_RGBA8 0x8058
#define GL_RGBA32F 0x8814
#define GL_ARRAY_BUFFER 0x8892
#define GL_ELEMENT_ARRAY_BUFFER 0x8893
#define GL_TRANSFORM_FEEDBACK_BUFFER 0x8c8e
#define GL_INTERLEAVED_ATTRIBS 0x8c8c
#define GL_RASTERIZER_DISCARD 0x8c89
#define GL_DYNAMIC_COPY 0x88ea
#define GL_STATIC_DRAW 0x88e4

#define GL_PROC(ret, name, args) static ret (APIENTRY *name) args
GL_PROC(GLuint, glCreateShader, (GLenum));
GL_PROC(void, glShaderSource, (GLuint, GLsizei, const char *const *, const GLint *));
GL_PROC(void, glCompileShader, (GLuint));
GL_PROC(void, glGetShaderiv, (GLuint, GLenum, GLint *));
GL_PROC(void, glGetShaderInfoLog, (GLuint, GLsizei, GLsizei *, char *));
GL_PROC(GLuint, glCreateProgram, (void));
GL_PROC(void, glAttachShader, (GLuint, GLuint));
GL_PROC(void, glLinkProgram, (GLuint));
GL_PROC(void, glGetProgramiv, (GLuint, GLenum, GLint *));
GL_PROC(void, glGetProgramInfoLog, (GLuint, GLsizei, GLsizei *, char *));
GL_PROC(void, glUseProgram, (GLuint));
GL_PROC(void, glGenVertexArrays, (GLsizei, GLuint *));
GL_PROC(void, glBindVertexArray, (GLuint));
GL_PROC(void, glGenFramebuffers, (GLsizei, GLuint *));
GL_PROC(void, glBindFramebuffer, (GLenum, GLuint));
GL_PROC(void, glFramebufferTexture2D, (GLenum, GLenum, GLenum, GLuint, GLint));
GL_PROC(GLenum, glCheckFramebufferStatus, (GLenum));
GL_PROC(void, glDeleteFramebuffers, (GLsizei, const GLuint *));
GL_PROC(void, glDeleteVertexArrays, (GLsizei, const GLuint *));
GL_PROC(void, glDeleteProgram, (GLuint));
GL_PROC(void, glDeleteShader, (GLuint));
GL_PROC(void, glGenBuffers, (GLsizei, GLuint *));
GL_PROC(void, glBindBuffer, (GLenum, GLuint));
GL_PROC(void, glBufferData, (GLenum, ptrdiff_t, const void *, GLenum));
GL_PROC(void, glGetBufferSubData, (GLenum, ptrdiff_t, ptrdiff_t, void *));
GL_PROC(void, glBindBufferRange, (GLenum, GLuint, GLuint, ptrdiff_t, ptrdiff_t));
GL_PROC(void, glTransformFeedbackVaryings, (GLuint, GLsizei, const char *const *, GLenum));
GL_PROC(void, glBeginTransformFeedback, (GLenum));
GL_PROC(void, glEndTransformFeedback, (void));
GL_PROC(void, glEnableVertexAttribArray, (GLuint));
GL_PROC(void, glVertexAttribPointer, (GLuint, GLint, GLenum, GLboolean, GLsizei, const void *));
GL_PROC(void, glVertexAttribIPointer, (GLuint, GLint, GLenum, GLsizei, const void *));
GL_PROC(void, glDeleteBuffers, (GLsizei, const GLuint *));

static void fail(const char *stage)
{
    fprintf(stderr, "[opengl-probe] FAIL: %s (Win32=%lu)\n", stage, GetLastError());
    exit(1);
}

static PROC gl_proc(const char *name)
{
    PROC p = wglGetProcAddress(name);
    if (!p || p == (PROC)1 || p == (PROC)2 || p == (PROC)3 || p == (PROC)-1)
        fail(name);
    return p;
}

#define LOAD(name) name = (void *)gl_proc(#name)

static GLuint shader(GLenum type, const char *source)
{
    GLuint s = glCreateShader(type);
    GLint ok = 0;
    glShaderSource(s, 1, &source, NULL);
    glCompileShader(s);
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "[opengl-probe] shader: %s\n", log);
        fail("compile GLSL 330");
    }
    return s;
}

static void pixel(const unsigned char *p, int r, int g, int b, const char *stage)
{
    printf("[opengl-probe] %s: RGBA=%u,%u,%u,%u\n", stage, p[0], p[1], p[2], p[3]);
    if (abs((int)p[0] - r) > 3 || abs((int)p[1] - g) > 3 ||
        abs((int)p[2] - b) > 3 || p[3] < 252) fail(stage);
}

static GLuint link_program(GLuint vert, GLuint frag, int feedback)
{
    GLuint p = glCreateProgram();
    glAttachShader(p, vert);
    if (frag) glAttachShader(p, frag);
    if (feedback) {
        const char *varyings[] = {"out_vertex", "out_packed"};
        glTransformFeedbackVaryings(p, 2, varyings, GL_INTERLEAVED_ATTRIBS);
    }
    glLinkProgram(p);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(p, sizeof(log), NULL, log);
        fprintf(stderr, "[opengl-probe] feedback link: %s\n", log);
        fail("link feedback program");
    }
    return p;
}

/* A Godot-style data-only VS: texture-driven vertex transforms, normalized
 * bone weights, mixed float/uint feedback, and no gl_Position or fragment
 * stage. Text/VertexID triangles alone cannot validate this rendering path. */
static void point_feedback(void)
{
    LOAD(glGenBuffers); LOAD(glBindBuffer); LOAD(glBufferData);
    LOAD(glGetBufferSubData); LOAD(glBindBufferRange);
    LOAD(glTransformFeedbackVaryings); LOAD(glBeginTransformFeedback);
    LOAD(glEndTransformFeedback); LOAD(glEnableVertexAttribArray);
    LOAD(glVertexAttribPointer); LOAD(glVertexAttribIPointer); LOAD(glDeleteBuffers);
    GLuint vs = shader(GL_VERTEX_SHADER, "#version 330 core\n"
        "layout(location=0) in vec3 p;layout(location=1) in vec2 weights;"
        "uniform sampler2D bones;out vec3 out_vertex;flat out uvec2 out_packed;"
        "void main(){out_vertex=p*texelFetch(bones,ivec2(0),0).xyz;"
        "out_packed=uvec2(99u,uint(weights.x*65535.0+0.5));}");
    GLuint program = link_program(vs, 0, 1);
    struct input { float p[3]; unsigned short weights[2]; } inputs[] = {
        {{-99,-99,-99}, {0,0}},
        {{-0.5f,-0.5f,0}, {65535,32768}},
        {{1.5f,-0.5f,0}, {65535,32768}},
        {{-0.5f,1.5f,0}, {65535,32768}}
    };
    struct output { float p[3]; unsigned packed[2]; } values[3];
    if (sizeof(values[0]) != 20 || sizeof(inputs[0]) != 16) fail("probe structure layout");
    GLuint vao, buffers[3], bone_texture;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(3, buffers);
    glBindBuffer(GL_ARRAY_BUFFER, buffers[0]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(inputs), inputs, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0); glEnableVertexAttribArray(1);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(inputs[0]), (void *)0);
    glVertexAttribPointer(1, 2, GL_UNSIGNED_SHORT, GL_TRUE, sizeof(inputs[0]), (void *)12);
    glGenTextures(1, &bone_texture); glBindTexture(GL_TEXTURE_2D, bone_texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    float bone[4] = {2,2,1,0};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, 1, 1, 0, GL_RGBA, GL_FLOAT, bone);
    glUseProgram(program);
    unsigned char guard[96], readback[96];
    memset(guard, 0xcd, sizeof(guard));
    for (unsigned pass = 0; pass < 3; ++pass) {
        unsigned count = pass == 2 ? 2 : 3;
        bone[0] = bone[1] = pass ? 1 : 2;
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 1, 1, GL_RGBA, GL_FLOAT, bone);
        glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER, buffers[1]);
        glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER, sizeof(guard), guard, GL_DYNAMIC_COPY);
        glBindBufferRange(GL_TRANSFORM_FEEDBACK_BUFFER, 0, buffers[1], 16, count * 20);
        glEnable(GL_RASTERIZER_DISCARD);
        glBeginTransformFeedback(GL_POINTS);
        if (!pass) {
            glDrawArrays(GL_POINTS, 1, 2);
            glDrawArrays(GL_POINTS, 3, 1); // append; VertexID must be rebased per draw
        } else {
            glDrawArrays(GL_POINTS, 1, 3); // pass 2 intentionally overflows by one vertex
        }
        glEndTransformFeedback();
        glDisable(GL_RASTERIZER_DISCARD);
        glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER, 0, sizeof(readback), readback);
        memcpy(values, readback + 16, count * 20);
        for (unsigned i = 0; i < sizeof(readback); ++i)
            if ((i < 16 || i >= 16 + count * 20) && readback[i] != 0xcd)
                fail("feedback buffer range/sentinel");
        for (unsigned i = 0; i < count; ++i) {
            for (unsigned c = 0; c < 3; ++c) {
                float expected = inputs[1+i].p[c] * bone[c];
                if (!(values[i].p[c] >= expected - 0.0001f &&
                      values[i].p[c] <= expected + 0.0001f)) {
                    fprintf(stderr, "[opengl-probe] pass %u vertex %u component %u: got %g expected %g\n",
                            pass, i, c, values[i].p[c], expected);
                    fail("feedback vertex values");
                }
            }
            if (values[i].packed[0] != 99 || values[i].packed[1] != 65535)
                fail("feedback integer/normalized attributes");
        }
        printf("[opengl-probe] PASS: point feedback %u (range, append/reset, texture and packed values)\n", pass);
    }
    // Refill the output with a full-screen triangle, then consume it as actual
    // vertex data through a 16-bit index buffer with a nonzero index offset.
    bone[0] = bone[1] = 2;
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 1, 1, GL_RGBA, GL_FLOAT, bone);
    glBindBufferRange(GL_TRANSFORM_FEEDBACK_BUFFER, 0, buffers[1], 16, 60);
    glEnable(GL_RASTERIZER_DISCARD); glBeginTransformFeedback(GL_POINTS);
    glDrawArrays(GL_POINTS, 1, 3);
    glEndTransformFeedback(); glDisable(GL_RASTERIZER_DISCARD);
    glBindBufferRange(GL_TRANSFORM_FEEDBACK_BUFFER, 0, 0, 0, 0);
    GLuint draw_vs = shader(GL_VERTEX_SHADER, "#version 330 core\n"
        "layout(location=0) in vec3 p;layout(location=1) in uvec2 packed_data;"
        "flat out uvec2 code;void main(){gl_Position=vec4(p,1);code=packed_data;}");
    GLuint draw_fs = shader(GL_FRAGMENT_SHADER, "#version 330 core\n"
        "flat in uvec2 code;out vec4 color;void main(){"
        "color=all(equal(code,uvec2(99u,65535u)))?vec4(0.25,0.5,0.75,1):vec4(1,0,1,1);}");
    GLuint draw_program = link_program(draw_vs, draw_fs, 0);
    glUseProgram(draw_program);
    glBindBuffer(GL_ARRAY_BUFFER, buffers[1]);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 20, (void *)16);
    glVertexAttribIPointer(1, 2, GL_UNSIGNED_INT, 20, (void *)28);
    unsigned short indices[] = {999,0,1,2};
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, buffers[2]);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(indices), indices, GL_STATIC_DRAW);
    glClearColor(1,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, (void *)2);
    unsigned char rgba[4] = {0};
    glReadPixels(8,8,1,1,GL_RGBA,GL_UNSIGNED_BYTE,rgba);
    pixel(rgba,64,128,191,"feedback vertices -> indexed draw/readback");
    if (glGetError() != GL_NO_ERROR) fail("GL error after transform feedback");
    glDeleteProgram(program); glDeleteProgram(draw_program);
    glDeleteShader(vs); glDeleteShader(draw_vs); glDeleteShader(draw_fs);
    glDeleteBuffers(3,buffers); glDeleteTextures(1,&bone_texture);
    glDeleteVertexArrays(1,&vao);
    puts("[opengl-probe] PASS: GPU point transform feedback and indexed geometry");
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    WNDCLASSA cls = {0};
    cls.style = CS_OWNDC;
    cls.lpfnWndProc = DefWindowProcA;
    cls.hInstance = GetModuleHandleW(NULL);
    cls.lpszClassName = "iDeckOpenGLProbe";
    if (!RegisterClassA(&cls)) fail("register window");
    HWND hwnd = CreateWindowA(cls.lpszClassName, "iDeck OpenGL probe", WS_POPUP,
                              0, 0, 64, 64, NULL, NULL, cls.hInstance, NULL);
    if (!hwnd) fail("create hidden window");
    HDC dc = GetDC(hwnd);
    PIXELFORMATDESCRIPTOR pfd = {0};
    pfd.nSize = sizeof(pfd);
    pfd.nVersion = 1;
    pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pfd.iPixelType = PFD_TYPE_RGBA;
    /* Match Godot's normal, non-layered window configuration. */
    pfd.cColorBits = 24;
    pfd.cDepthBits = 24;
    /* Wine's GDI32 forwards these calls to the replacement's wgl* exports.
     * Use that same path on a Windows host, whose system GDI uses ICDs. */
    HMODULE gl = GetModuleHandleW(L"opengl32.dll");
    char module_path[MAX_PATH] = {0};
    GetModuleFileNameA(gl, module_path, sizeof(module_path));
    printf("[opengl-probe] opengl32=%s\n", module_path);
    int (WINAPI *choose_format)(HDC, const PIXELFORMATDESCRIPTOR *) =
        (void *)GetProcAddress(gl, "wglChoosePixelFormat");
    BOOL (WINAPI *set_format)(HDC, int, const PIXELFORMATDESCRIPTOR *) =
        (void *)GetProcAddress(gl, "wglSetPixelFormat");
    int (WINAPI *get_format)(HDC) = (void *)GetProcAddress(gl, "wglGetPixelFormat");
    int (WINAPI *describe_format)(HDC, int, UINT, PIXELFORMATDESCRIPTOR *) =
        (void *)GetProcAddress(gl, "wglDescribePixelFormat");
    if (!choose_format || !set_format || !get_format || !describe_format)
        fail("Mesa WGL exports");
    int format = choose_format(dc, &pfd);
    if (!format) fail("choose pixel format");
    if (!set_format(dc, format, &pfd)) fail("set pixel format");
    /* Godot sets the window format, then repeats it during context creation. */
    if (!set_format(dc, format, &pfd)) fail("repeat identical pixel format");
    PIXELFORMATDESCRIPTOR other = {0};
    int alternative = format == 1 ? 2 : 1;
    if (describe_format(dc, alternative, sizeof(other), &other) < alternative)
        fail("describe alternative pixel format");
    if (set_format(dc, alternative, &other)) fail("different pixel format accepted");
    if (get_format(dc) != format) fail("window pixel format changed");
    puts("[opengl-probe] PASS: repeated pixel format accepted; format change rejected");
    HGLRC bootstrap = wglCreateContext(dc);
    if (!bootstrap || !wglMakeCurrent(dc, bootstrap)) fail("bootstrap context");
    HGLRC (WINAPI *create_context)(HDC, HGLRC, const int *) =
        (void *)gl_proc("wglCreateContextAttribsARB");
    const int attribs[] = {0x2091, 3, 0x2092, 3, 0x9126, 1, 0};
    HGLRC context = create_context(dc, NULL, attribs);
    if (!context || !wglMakeCurrent(dc, context)) fail("OpenGL 3.3 core context");
    wglDeleteContext(bootstrap);
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    const char *version = (const char *)glGetString(GL_VERSION);
    printf("[opengl-probe] version=%s renderer=%s\n", version ? version : "null",
           renderer ? renderer : "null");
    if (!renderer || !strstr(renderer, "D3D12")) fail("expected Mesa D3D12 renderer");
    LOAD(glCreateShader); LOAD(glShaderSource); LOAD(glCompileShader);
    LOAD(glGetShaderiv); LOAD(glGetShaderInfoLog); LOAD(glCreateProgram);
    LOAD(glAttachShader); LOAD(glLinkProgram); LOAD(glGetProgramiv);
    LOAD(glGetProgramInfoLog); LOAD(glUseProgram); LOAD(glGenVertexArrays);
    LOAD(glBindVertexArray); LOAD(glGenFramebuffers); LOAD(glBindFramebuffer);
    LOAD(glFramebufferTexture2D); LOAD(glCheckFramebufferStatus);
    LOAD(glDeleteFramebuffers); LOAD(glDeleteVertexArrays);
    LOAD(glDeleteProgram); LOAD(glDeleteShader);
    const char *vs = "#version 330 core\n"
        "void main(){vec2 p[3]=vec2[](vec2(-1,-1),vec2(3,-1),vec2(-1,3));"
        "gl_Position=vec4(p[gl_VertexID],0,1);}";
    const char *fs = "#version 330 core\n"
        "out vec4 color;void main(){color=vec4(0.25,0.5,0.75,1);}";
    GLuint vert = shader(GL_VERTEX_SHADER, vs), frag = shader(GL_FRAGMENT_SHADER, fs);
    GLuint program = glCreateProgram();
    glAttachShader(program, vert); glAttachShader(program, frag); glLinkProgram(program);
    GLint ok = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(program, sizeof(log), NULL, log);
        fprintf(stderr, "[opengl-probe] link: %s\n", log);
        fail("link program");
    }
    GLuint vao, texture, fbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_2D, texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 16, 16, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glGenFramebuffers(1, &fbo); glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fail("framebuffer");
    glViewport(0, 0, 16, 16);
    glClearColor(1, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    unsigned char rgba[4] = {0};
    glReadPixels(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    pixel(rgba, 255, 0, 0, "FBO clear/readback");
    glUseProgram(program); glDrawArrays(GL_TRIANGLES, 0, 3);
    glReadPixels(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    pixel(rgba, 64, 128, 191, "GLSL draw/readback");
    point_feedback();
    glBindVertexArray(vao); glUseProgram(program);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0, 0, 64, 64);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    pixel(rgba, 64, 128, 191, "window draw/readback");
    BOOL (WINAPI *swap_buffers)(HDC) = (void *)GetProcAddress(gl, "wglSwapBuffers");
    if (!swap_buffers || !swap_buffers(dc)) fail("swap buffers");
    if (glGetError() != GL_NO_ERROR) fail("GL error after present");
    glDeleteFramebuffers(1, &fbo); glDeleteTextures(1, &texture);
    glDeleteVertexArrays(1, &vao); glDeleteProgram(program);
    glDeleteShader(vert); glDeleteShader(frag);
    wglMakeCurrent(NULL, NULL); wglDeleteContext(context);
    ReleaseDC(hwnd, dc); DestroyWindow(hwnd); UnregisterClassA(cls.lpszClassName, cls.hInstance);
    puts("[opengl-probe] PASS: pixel format, OpenGL 3.3, GLSL, FBO, readback and SwapBuffers");
    return 0;
}
