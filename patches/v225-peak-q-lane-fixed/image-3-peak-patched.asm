0008232c 04f0456c  ldw r1, cp[0x105]
00082330 02f041d1  bl 0x941 ; div_f32 -> 0x84838
00082334 01f004d2  bl 0x604 ; f32_to_f64 -> 0x83b48
00082338 2090ff17  add r2, r0, 0 ; nop
0008233c 3490ff17  add r3, r1, 0 ; nop
00082340 0068ff17  ldc r0, 0 ; nop
00082344 04f0476c  ldw r1, cp[0x107]
00082348 01f0c2d2  bl 0x6c2 ; pow_f64 -> 0x83e54
0008234c 01f0d6d0  bl 0x4d6 ; f64_to_f32 -> 0x836a8
00082350 ff170454  nop ; stw r0, sp[4]
00082354 8491ff17  add r0, r9, 0 ; nop
00082358 01f0fbd1  bl 0x5fb ; f32_to_f64 -> 0x83b48
0008235c 05f08d6c  ldw r2, cp[0x14d]
00082360 01f0dc6c  ldw r3, cp[0x5c]
00082364 01f018d2  bl 0x618 ; mul_f64 -> 0x83bc8
00082368 9090ff17  add r9, r0, 0 ; nop
0008236c a490ff17  add r10, r1, 0 ; nop
00082370 8091ff17  add r0, r8, 0 ; nop
00082374 01f0f4d1  bl 0x5f4 ; f32_to_f64 -> 0x83b48
00082378 2090ff17  add r2, r0, 0 ; nop
0008237c 3490ff17  add r3, r1, 0 ; nop
00082380 8491ff17  add r0, r9, 0 ; nop
00082384 9891ff17  add r1, r10, 0 ; nop
00082388 01f017d0  bl 0x417 ; div_f64 -> 0x833e8
0008238c 02f01dd0  bl 0x81d ; tan_f64 -> 0x84404
00082390 01f0c5d0  bl 0x4c5 ; f64_to_f32 -> 0x836a8
00082394 8090ff17  add r8, r0, 0 ; nop
00082398 dc90ff17  add r1, r7, 0 ; nop
0008239c 02f026d1  bl 0x926 ; div_f32 -> 0x84838
000823a0 7090ff17  add r7, r0, 0 ; nop
000823a4 ff17445c  nop ; ldw r1, sp[4]
000823a8 02f023d1  bl 0x923 ; div_f32 -> 0x84838
000823ac 9090ff17  add r9, r0, 0 ; nop
000823b0 04f0976d  ldw r6, cp[0x117]
000823b4 80feedb7  fmul r8, r8, r8
000823b8 62fceeb7  fadd r10, r8, r6
000823bc 19feeeb7  fadd r1, r10, r9
000823c0 c890ff17  add r0, r6, 0 ; nop
000823c4 02f01cd1  bl 0x91c ; div_f32 -> 0x84838
000823c8 6090ff17  add r6, r0, 0 ; nop
000823cc ff17045c  nop ; ldw r0, sp[4]
000823d0 3cf9edb7  fmul r7, r7, r0
000823d4 cbfbeeb7  fadd r0, r10, r7
000823d8 42faedb7  fmul r0, r0, r6
000823dc ff170454  nop ; stw r0, sp[4]
000823e0 cbfbefb7  fsub r0, r10, r7
000823e4 42faedb7  fmul r0, r0, r6
000823e8 04f0576c  ldw r1, cp[0x117]
000823ec 01faefb7  fsub r8, r8, r1
000823f0 80feeeb7  fadd r8, r8, r8
000823f4 42fcedb7  fmul r8, r8, r6
000823f8 19feefb7  fsub r1, r10, r9
000823fc 56faedb7  fmul r1, r1, r6
00082400 ff174354  nop ; stw r1, sp[3]
00082404 ff17ff17  nop ; nop
00082408 ff17ff17  nop ; nop
0008240c ff17ff17  nop ; nop
00082410 ff17ff17  nop ; nop
00082414 ff17ff17  nop ; nop
00082418 ff17ff17  nop ; nop
0008241c ff17ff17  nop ; nop
00082420 ff17ff17  nop ; nop
00082424 ff17ff17  nop ; nop
00082428 ff17ff17  nop ; nop
0008242c ff17ff17  nop ; nop
00082430 ff17ff17  nop ; nop
00082434 ff17ff17  nop ; nop
00082438 ff17ff17  nop ; nop
0008243c ff17ff17  nop ; nop
00082440 ff17ff17  nop ; nop
00082444 ff17ff17  nop ; nop
00082448 ff17ff17  nop ; nop
0008244c ff17ff17  nop ; nop
00082450 ff17ff17  nop ; nop
00082454 ff17ff17  nop ; nop
00082458 ff17ff17  nop ; nop
0008245c ff17ff17  nop ; nop
00082460 ff17ff17  nop ; nop
00082464 ff17ff17  nop ; nop
00082468 ff17ff17  nop ; nop
0008246c ff17ff17  nop ; nop
00082470 ff17ff17  nop ; nop
00082474 ff17ff17  nop ; nop
00082478 ff17ff17  nop ; nop
0008247c ff17ff17  nop ; nop
00082480 ff17ff17  nop ; nop
00082484 ff17ff17  nop ; nop
