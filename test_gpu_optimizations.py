"""GPU Optimization Test Script

Quick test to verify the GPU optimizations are working correctly.
Run this after loading the game to check optimization status.
"""

def test_gpu_optimizations():
    """Test GPU optimization features."""
    try:
        import shader
        import sprite_manager as sm
        
        print("="*60)
        print("GPU OPTIMIZATION TEST")
        print("="*60)
        
        # Test 1: Check shader engine is available
        engine = shader.get_shader_engine()
        if engine is None:
            print("❌ FAIL: Shader engine not initialized")
            print("   → Call shader.get_lighting_engine() first")
            return False
        else:
            print("✓ PASS: Shader engine initialized")
        
        # Test 2: Check mode
        stats = engine.get_stats()
        print(f"  Mode: {stats['mode']}")
        print(f"  GPU initialized: {stats['gpu_initialized']}")
        
        # Test 3: Test dirty marking
        print("\n--- Testing Dirty Tracking ---")
        initial_dirty = stats['dirty_tiles']
        shader.mark_sprite_dirty(10, 20)
        stats = engine.get_stats()
        if stats['dirty_tiles'] > initial_dirty:
            print("✓ PASS: Dirty tracking works")
        else:
            print("❌ FAIL: Dirty tracking not working")
        
        # Test 4: Test cache invalidation
        print("\n--- Testing Cache Invalidation ---")
        initial_cache = stats['cached_materials']
        shader.invalidate_material_cache(0xE000)
        stats = engine.get_stats()
        print(f"  Cached materials: {stats['cached_materials']}")
        print("✓ PASS: Cache invalidation callable")
        
        # Test 5: Test sprite manager integration
        print("\n--- Testing Sprite Manager Integration ---")
        shader_mod = sm._get_shader()
        if shader_mod is not None:
            print("✓ PASS: Sprite manager can access shader module")
        else:
            print("⚠ WARNING: Sprite manager shader integration not active")
        
        # Test 6: Display final stats
        print("\n--- Final Statistics ---")
        stats = engine.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        print("\n="*60)
        print("OPTIMIZATION TEST COMPLETE")
        print("="*60)
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_gpu_optimizations()
